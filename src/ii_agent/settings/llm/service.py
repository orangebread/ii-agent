"""Service layer for llm_settings domain - business logic only."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.core.secrets.encryption import encryption_manager
from ii_agent.settings.llm.catalog import (
    MANAGED_MODEL_CATALOG_BY_PROVIDER_AND_ID,
    MANAGED_MODEL_CATALOG_BY_SETTING_ID,
    MANAGED_PROVIDER_MODEL_CATALOG,
)
from ii_agent.settings.llm.exceptions import LLMSettingNotFoundError, LLMSettingUnavailableError
from ii_agent.settings.llm.models import ModelSetting
from ii_agent.settings.llm.repository import ModelSettingRepository
from ii_agent.settings.llm.schemas import (
    LLMModelInfo,
    LLMModelList,
    ModelConfig,
    ModelParams,
    ModelSettingCreate,
    ModelSettingInfo,
    ModelSettingInfoWithKey,
    ModelSettingList,
    ModelSettingUpdate,
    PricingInfo,
)
from ii_agent.settings.llm.types import (
    ApiType,
    ConfigType,
    CredentialSource,
    ModelAvailabilityStatus,
    Provider,
)

if TYPE_CHECKING:
    from ii_agent.sessions.repository import SessionRepository
    from ii_agent.sessions.schemas import SessionInfo
    from ii_agent.settings.provider_connections.models import ProviderConnection
    from ii_agent.settings.provider_connections.service import ProviderConnectionService


# Backward-compatible alias used by older tests/callers.
LLMSettingRepository = ModelSettingRepository


@dataclass(frozen=True)
class ProviderManagedExecutionState:
    """Resolved execution state for provider-backed model rows."""

    availability_status: ModelAvailabilityStatus
    disabled_reason: str | None = None
    api_key: SecretStr | None = None
    auth_token: SecretStr | None = None
    base_url: str | None = None
    default_headers: dict[str, str] | None = None
    runtime_product: str | None = None


class ModelSettingService:
    """Service for managing LLM settings - business logic layer."""

    def __init__(
        self,
        *,
        repo: ModelSettingRepository,
        session_repo: SessionRepository,
        provider_connection_service: ProviderConnectionService | None = None,
        config: object | None = None,
    ) -> None:
        self._repo = repo
        self._session_repo = session_repo
        self._provider_connection_service = provider_connection_service
        self._config = config

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_model_settings(
        self,
        db: AsyncSession,
        *,
        model_setting_request: ModelSettingCreate,
        user_id: uuid.UUID,
    ) -> ModelSettingInfo:
        """Create or upsert model settings for a specific model."""
        await self._sync_provider_managed_models(db, user_id=user_id)

        existing = await self._repo_find_by_model_and_user(
            db, model_setting_request.model_id, user_id=user_id
        )

        encrypted_api_key = encryption_manager.encrypt(model_setting_request.api_key)
        configs_dict = (
            model_setting_request.configs.model_dump(exclude_none=True)
            if model_setting_request.configs
            else None
        )
        pricing_dict = (
            model_setting_request.pricing.model_dump() if model_setting_request.pricing else None
        )

        if existing:
            existing.provider = model_setting_request.provider
            existing.encrypted_api_key = encrypted_api_key
            existing.provider_connection_id = None
            existing.base_url = model_setting_request.base_url
            existing.display_name = model_setting_request.display_name
            _set_setting_params(existing, configs_dict)
            existing.pricing = pricing_dict
            existing.config_type = model_setting_request.config_type
            existing.is_default = model_setting_request.is_default
            existing.is_active = model_setting_request.is_active
            existing.updated_at = datetime.now(timezone.utc)

            updated = await self._repo.update(db, existing)
            return _to_model_setting_info(updated)

        new_setting = ModelSetting(
            user_id=user_id,
            model_id=model_setting_request.model_id,
            provider=model_setting_request.provider,
            encrypted_api_key=encrypted_api_key,
            provider_connection_id=None,
            base_url=model_setting_request.base_url,
            display_name=model_setting_request.display_name,
            params=configs_dict,
            pricing=pricing_dict,
            config_type=model_setting_request.config_type,
            is_default=model_setting_request.is_default,
            is_active=model_setting_request.is_active,
        )
        _set_setting_params(new_setting, configs_dict)

        created = await self._repo.create(db, new_setting)
        if getattr(created, "id", None) is None:
            created.id = uuid.uuid4()
        return _to_model_setting_info(created)

    async def update_model_settings(
        self,
        db: AsyncSession,
        *,
        setting_id: uuid.UUID,
        setting_update: ModelSettingUpdate,
        user_id: uuid.UUID,
    ) -> ModelSettingInfo:
        """Update existing model settings.

        Raises:
            LLMSettingNotFoundError: If setting not found or access denied.
        """
        await self._sync_provider_managed_models(db, user_id=user_id)

        setting = await self._repo_find_by_id_and_user_id(db, setting_id, user_id)
        if not setting:
            raise LLMSettingNotFoundError(f"Model setting {setting_id} not found or access denied")

        if setting_update.api_key is not None:
            setting.encrypted_api_key = encryption_manager.encrypt(setting_update.api_key)
            setting.provider_connection_id = None
        if setting_update.base_url is not None:
            setting.base_url = setting_update.base_url
        if setting_update.display_name is not None:
            setting.display_name = setting_update.display_name
        if setting_update.configs is not None:
            _set_setting_params(setting, setting_update.configs.model_dump(exclude_none=True))
        if setting_update.pricing is not None:
            setting.pricing = setting_update.pricing.model_dump()
        if setting_update.config_type is not None:
            setting.config_type = setting_update.config_type
        if setting_update.is_default is not None:
            setting.is_default = setting_update.is_default
        if setting_update.is_active is not None:
            setting.is_active = setting_update.is_active

        setting.updated_at = datetime.now(timezone.utc)
        updated = await self._repo.update(db, setting)
        return _to_model_setting_info(updated)

    async def get_model_settings(
        self,
        db: AsyncSession,
        *,
        setting_id: uuid.UUID,
        user_id: uuid.UUID,
        include_key: bool = False,
    ) -> ModelSettingInfoWithKey | ModelSettingInfo | None:
        """Get model settings by ID."""
        await self._sync_provider_managed_models(db, user_id=user_id)

        setting = await self._repo_find_by_id_and_user_id(db, setting_id, user_id)
        if not setting:
            return None

        return _to_model_setting_info(setting, include_key=include_key)

    async def get_model_settings_by_name(
        self,
        db: AsyncSession,
        *,
        model_name: str,
        user_id: uuid.UUID,
        include_key: bool = False,
    ) -> ModelSettingInfoWithKey | ModelSettingInfo | None:
        """Get model settings by model_id string."""
        await self._sync_provider_managed_models(db, user_id=user_id)

        setting = await self._repo_find_by_model_and_user(db, model_name, user_id)
        if not setting:
            setting = await self._repo_find_by_visible_model_and_user(
                db,
                model_name,
                user_id=user_id,
            )
        if not setting:
            return None

        return _to_model_setting_info(setting, include_key=include_key)

    async def list_model_settings(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        provider: str | None = None,
    ) -> ModelSettingList:
        """List all model settings for a user."""
        await self._sync_provider_managed_models(db, user_id=user_id)

        settings = await self._repo_find_all_by_user(db, user_id, provider=provider)
        model_list = [_to_model_setting_info(s) for s in settings]
        return ModelSettingList(models=model_list)

    async def delete_model_settings(
        self,
        db: AsyncSession,
        *,
        model_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete model settings by ID."""
        setting = await self._repo_find_by_id_and_user_id(db, model_id, user_id)
        if not setting:
            return False

        await self._repo.delete(db, setting)
        return True

    # ------------------------------------------------------------------
    # Aggregation / resolution
    # ------------------------------------------------------------------

    async def get_all_available_models(
        self, db: AsyncSession, *, user_id: uuid.UUID
    ) -> LLMModelList:
        """Get all available models from DB (system + user settings)."""
        await self._sync_provider_managed_models(db, user_id=user_id)

        models: list[LLMModelInfo] = []

        system_rows = await self._repo_find_all_system_models(db)
        for row in system_rows:
            models.append(await self._to_llm_model_info(db, setting=row, user_id=user_id))

        user_rows = await self._repo_find_all_by_user(db, user_id)
        for row in user_rows:
            models.append(await self._to_llm_model_info(db, setting=row, user_id=user_id))

        return LLMModelList(models=models)

    async def get_user_model_config(
        self,
        db: AsyncSession,
        *,
        setting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ModelConfig:
        """Get a user model config from the database."""
        await self._sync_provider_managed_models(db, user_id=user_id)

        setting = await self._repo_find_by_id_and_user_id(db, setting_id, user_id)
        if not setting:
            raise ValueError(f"LLM setting not found: {setting_id}")
        return await self._setting_to_model_config(db, setting=setting, user_id=user_id)

    async def resolve_system_config(self, db: AsyncSession, *, model_id: str) -> ModelConfig:
        """Resolve a system model config from DB by model_id."""
        setting = await self._repo_find_system_by_model_id(db, model_id)
        if not setting:
            raise ValueError(f"System model config not found for model: {model_id}")
        return await self._setting_to_model_config(db, setting=setting, user_id=setting.user_id)

    async def resolve_config_by_setting_id(
        self,
        db: AsyncSession,
        *,
        setting_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> ModelConfig:
        """Resolve a model config by its model_settings.id (user or system)."""
        setting = await self._resolve_accessible_setting(
            db,
            setting_id=setting_id,
            user_id=user_id,
        )
        if not setting:
            raise ValueError(f"Model setting not found: {setting_id}")
        effective_user_id = setting.user_id if setting.user_id is not None else user_id
        return await self._setting_to_model_config(
            db,
            setting=setting,
            user_id=effective_user_id,
        )

    async def resolve_model_config(
        self,
        db: AsyncSession,
        *,
        session: SessionInfo,
        source: str | None = None,
        model_id: str | None = None,
    ) -> ModelConfig:
        """Resolve the model config for an agent run."""
        await self._sync_provider_managed_models(db, user_id=session.user_id)

        if model_id:
            return await self._resolve_explicit_model_request(
                db,
                user_id=session.user_id,
                source=source,
                model_id=model_id,
            )

        current_session = await self._session_repo.get_by_id(db, session.id)
        model_setting_id = None
        if current_session is not None:
            model_setting_id = getattr(current_session, "model_setting_id", None) or getattr(
                current_session, "llm_setting_id", None
            )

        if model_setting_id is not None:
            return await self.resolve_config_by_setting_id(
                db,
                setting_id=model_setting_id,
                user_id=session.user_id,
            )

        raise ValueError("model_id is required when session has no model_setting_id")

    async def _resolve_explicit_model_request(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        source: str | None,
        model_id: str,
    ) -> ModelConfig:
        requested_setting_id = _try_parse_uuid(model_id)
        if requested_setting_id is not None:
            return await self.resolve_config_by_setting_id(
                db,
                setting_id=requested_setting_id,
                user_id=user_id,
            )

        if source == ConfigType.USER.value:
            setting = await self._repo_find_by_model_and_user(db, model_id, user_id)
            if not setting:
                setting = await self._repo_find_by_visible_model_and_user(
                    db,
                    model_id,
                    user_id=user_id,
                )
            if not setting:
                raise ValueError(f"Model setting not found: {model_id}")
            return await self._setting_to_model_config(db, setting=setting, user_id=user_id)

        return await self.resolve_system_config(db, model_id=model_id)

    async def _resolve_accessible_setting(
        self,
        db: AsyncSession,
        *,
        setting_id: uuid.UUID,
        user_id: uuid.UUID | None,
    ) -> ModelSetting | None:
        if user_id is not None:
            setting = await self._repo_find_by_id_and_user_id(db, setting_id, user_id)
            if setting:
                return setting

        setting = await self._repo.get_by_id(db, setting_id)
        if setting is None:
            return None
        if user_id is None:
            return setting
        if setting.user_id is None and setting.config_type == ConfigType.SYSTEM.value:
            return setting
        return None

    async def _sync_provider_managed_models(self, db: AsyncSession, *, user_id: uuid.UUID) -> None:
        if self._provider_connection_service is None:
            return

        dirty = False
        now = datetime.now(timezone.utc)

        for (provider, runtime_product), catalog_entries in MANAGED_PROVIDER_MODEL_CATALOG.items():
            provider_dirty = await self._sync_provider_managed_catalog(
                db,
                user_id=user_id,
                provider=provider,
                runtime_product=runtime_product,
                catalog_entries=catalog_entries,
                now=now,
            )
            dirty = dirty or provider_dirty

        if dirty:
            await db.flush()

    async def _sync_provider_managed_catalog(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        provider: str,
        runtime_product: str,
        catalog_entries,
        now: datetime,
    ) -> bool:
        connection = await self._provider_connection_service.get_by_provider_product(
            db,
            user_id=user_id,
            provider=provider,
            product=runtime_product,
        )
        managed_rows = await self._repo.find_provider_managed_by_user(
            db,
            user_id,
            provider=provider,
        )
        catalog_by_model = {entry.model_id: entry for entry in catalog_entries}
        dirty = False

        if (
            connection is None
            or not self._provider_connection_service.supports_provider_managed_model_catalog(
                connection
            )
        ):
            for row in managed_rows:
                if _resolved_provider_model_id(row) in catalog_by_model:
                    await self._repo.delete(db, row)
                    dirty = True
            return dirty

        for row in managed_rows:
            entry = catalog_by_model.get(row.model_id)
            if entry is None:
                entry = catalog_by_model.get(_resolved_provider_model_id(row))
            if entry is None:
                await self._repo.delete(db, row)
                dirty = True
                continue
            row.model_id = entry.setting_model_id
            row.provider = entry.provider.value
            row.provider_connection_id = connection.id
            row.display_name = entry.display_name
            params = ModelParams.model_validate(_get_setting_params(row) or {})
            params.provider_model_id = entry.model_id
            _set_setting_params(row, params.model_dump(exclude_none=True))
            row.pricing = (
                row.pricing
                or PricingInfo.get_default_pricing(entry.model_id, entry.provider).model_dump()
            )
            row.config_type = ConfigType.USER.value
            row.is_active = True
            row.updated_at = now
            dirty = True

        existing_managed_by_model = {_resolved_provider_model_id(row): row for row in managed_rows}

        for entry in catalog_entries:
            if entry.model_id in existing_managed_by_model:
                continue

            params = ModelParams(provider_model_id=entry.model_id).model_dump(exclude_none=True)
            db.add(
                ModelSetting(
                    user_id=user_id,
                    model_id=entry.setting_model_id,
                    provider=entry.provider.value,
                    encrypted_api_key=None,
                    provider_connection_id=connection.id,
                    base_url=None,
                    display_name=entry.display_name,
                    params=params,
                    pricing=PricingInfo.get_default_pricing(
                        entry.model_id, entry.provider
                    ).model_dump(),
                    config_type=ConfigType.USER.value,
                    is_default=False,
                    is_active=True,
                )
            )
            dirty = True

        return dirty

    async def _to_llm_model_info(
        self,
        db: AsyncSession,
        *,
        setting: ModelSetting,
        user_id: uuid.UUID,
    ) -> LLMModelInfo:
        credential_source = _credential_source(setting)
        availability_status = ModelAvailabilityStatus.AVAILABLE
        disabled_reason: str | None = None
        runtime_product = _managed_runtime_product(setting)

        if credential_source == CredentialSource.PROVIDER_OAUTH:
            provider_state = await self._provider_oauth_state(
                db,
                setting=setting,
                user_id=user_id,
            )
            availability_status = provider_state.availability_status
            disabled_reason = provider_state.disabled_reason
            runtime_product = provider_state.runtime_product
        else:
            api_key = _decrypt_api_key(setting)
            if api_key is None and not _supports_keyless_execution(setting):
                availability_status = ModelAvailabilityStatus.MISSING_CREDENTIALS
                disabled_reason = _missing_credentials_reason(setting)

        is_selectable = availability_status == ModelAvailabilityStatus.AVAILABLE and bool(
            setting.is_active
        )
        if not setting.is_active and disabled_reason is None:
            disabled_reason = "This model is currently disabled."

        pricing = PricingInfo.model_validate(setting.pricing) if setting.pricing else None
        return LLMModelInfo(
            id=setting.id,
            model_id=_resolved_provider_model_id(setting),
            model=_resolved_provider_model_id(setting),
            provider=setting.provider,
            source=setting.config_type,
            display_name=setting.display_name or _resolved_provider_model_id(setting),
            credential_source=credential_source,
            provider_connection_id=getattr(setting, "provider_connection_id", None),
            runtime_product=runtime_product,
            is_managed=getattr(setting, "provider_connection_id", None) is not None,
            is_selectable=is_selectable,
            availability_status=availability_status,
            disabled_reason=disabled_reason,
            base_url=setting.base_url,
            pricing=pricing,
        )

    async def _setting_to_model_config(
        self,
        db: AsyncSession,
        *,
        setting: ModelSetting,
        user_id: uuid.UUID | None,
    ) -> ModelConfig:
        credential_source = _credential_source(setting)
        api_key = _decrypt_api_key(setting)
        auth_token: SecretStr | None = None
        base_url = setting.base_url
        default_headers: dict[str, str] | None = None
        runtime_product = _managed_runtime_product(setting)

        if credential_source == CredentialSource.PROVIDER_OAUTH:
            provider_state = await self._provider_oauth_state(
                db,
                setting=setting,
                user_id=user_id,
            )
            if provider_state.availability_status != ModelAvailabilityStatus.AVAILABLE:
                raise LLMSettingUnavailableError(
                    provider_state.disabled_reason
                    or "This provider-backed model is not ready to execute.",
                    availability_status=provider_state.availability_status,
                )
            api_key = provider_state.api_key or api_key
            auth_token = provider_state.auth_token
            base_url = provider_state.base_url or base_url
            default_headers = provider_state.default_headers
            runtime_product = provider_state.runtime_product or runtime_product
        elif api_key is None and not _supports_keyless_execution(setting):
            raise LLMSettingUnavailableError(
                _missing_credentials_reason(setting),
                availability_status=ModelAvailabilityStatus.MISSING_CREDENTIALS,
            )

        return _build_model_config(
            setting,
            api_key=api_key,
            auth_token=auth_token,
            credential_source=credential_source,
            base_url=base_url,
            default_headers=default_headers,
            runtime_product=runtime_product,
        )

    async def _provider_oauth_state(
        self,
        db: AsyncSession,
        *,
        setting: ModelSetting,
        user_id: uuid.UUID | None,
    ) -> ProviderManagedExecutionState:
        if self._provider_connection_service is None:
            return ProviderManagedExecutionState(
                availability_status=ModelAvailabilityStatus.UNSUPPORTED,
                disabled_reason="Provider-backed model execution is not enabled on this deployment.",
            )

        if user_id is None or setting.provider_connection_id is None:
            return ProviderManagedExecutionState(
                availability_status=ModelAvailabilityStatus.REAUTH_REQUIRED,
                disabled_reason="Reconnect this provider before selecting the model again.",
            )

        connection = await self._provider_connection_service.get_connection_model(
            db,
            connection_id=setting.provider_connection_id,
            user_id=user_id,
        )
        if connection is None:
            return ProviderManagedExecutionState(
                availability_status=ModelAvailabilityStatus.REAUTH_REQUIRED,
                disabled_reason="Reconnect this provider before selecting the model again.",
            )

        if not _supports_provider_managed_execution(connection, setting):
            return ProviderManagedExecutionState(
                availability_status=ModelAvailabilityStatus.UNSUPPORTED,
                disabled_reason=_unsupported_provider_reason(setting, connection=connection),
                runtime_product=getattr(connection, "product", None),
            )

        credentials = self._provider_connection_service.get_live_model_credentials(connection)
        if credentials is not None:
            return ProviderManagedExecutionState(
                availability_status=ModelAvailabilityStatus.AVAILABLE,
                api_key=SecretStr(credentials.api_key) if credentials.api_key else None,
                auth_token=SecretStr(credentials.auth_token) if credentials.auth_token else None,
                base_url=credentials.base_url,
                default_headers=credentials.default_headers,
                runtime_product=credentials.runtime_product,
            )

        auth_state = self._provider_connection_service.describe_auth_state(connection)
        if auth_state.needs_reauth:
            return ProviderManagedExecutionState(
                availability_status=ModelAvailabilityStatus.REAUTH_REQUIRED,
                disabled_reason=_reauth_reason(connection),
                runtime_product=getattr(connection, "product", None),
            )

        return ProviderManagedExecutionState(
            availability_status=ModelAvailabilityStatus.MISSING_CREDENTIALS,
            disabled_reason="This OAuth connection does not have a live access token for model execution.",
            runtime_product=getattr(connection, "product", None),
        )

    async def get_user_llm_config(
        self,
        db: AsyncSession,
        *,
        setting_id: uuid.UUID | str | None = None,
        model_id: str | None = None,
        user_id: uuid.UUID,
    ) -> ModelConfig:
        """Backward-compatible alias for older callers/tests."""
        if setting_id is None and model_id is None:
            raise ValueError("LLM setting not found")

        if setting_id is None and model_id is not None:
            parsed_setting_id = _try_parse_uuid(model_id)
            if parsed_setting_id is not None:
                return await self.get_user_model_config(
                    db,
                    setting_id=parsed_setting_id,
                    user_id=user_id,
                )
            setting = await self._repo_find_by_model_and_user(db, model_id, user_id=user_id)
            if not setting:
                setting = await self._repo_find_by_visible_model_and_user(
                    db,
                    model_id,
                    user_id=user_id,
                )
            if not setting:
                raise ValueError(f"LLM setting not found: {model_id}")
            return await self._setting_to_model_config(db, setting=setting, user_id=user_id)

        return await self.get_user_model_config(
            db,
            setting_id=setting_id,
            user_id=user_id,
        )

    async def get_llm_settings(
        self,
        db: AsyncSession,
        *,
        session: SessionInfo,
        source: str | None = None,
        model_id: str | None = None,
    ) -> ModelConfig:
        """Backward-compatible alias for session-based config resolution."""
        current_session = await self._session_repo.get_by_id(db, session.id)
        current_setting_id = None
        if current_session is not None:
            current_setting_id = getattr(current_session, "model_setting_id", None) or getattr(
                current_session, "llm_setting_id", None
            )

        if current_setting_id is None:
            if source == ConfigType.USER.value and model_id:
                return await self.get_user_llm_config(
                    db,
                    model_id=model_id,
                    user_id=session.user_id,
                )
            if not model_id:
                raise ValueError("model_id is required when session has no model_setting_id")
            return await self.resolve_system_config(db, model_id=model_id)

        return await self.resolve_config_by_setting_id(
            db,
            setting_id=current_setting_id,
            user_id=session.user_id,
        )

    async def _repo_find_by_model_and_user(
        self,
        db: AsyncSession,
        model_id: str,
        user_id: uuid.UUID,
    ) -> ModelSetting | None:
        if hasattr(self._repo, "find_by_model_and_user"):
            return await self._repo.find_by_model_and_user(db, model_id, user_id)
        return await self._repo.get_by_model_and_user(db, model_id, user_id)

    async def _repo_find_by_id_and_user_id(
        self,
        db: AsyncSession,
        setting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ModelSetting | None:
        if hasattr(self._repo, "find_by_id_and_user_id"):
            return await self._repo.find_by_id_and_user_id(db, setting_id, user_id)
        return await self._repo.get_by_id_and_user(db, setting_id, user_id)

    async def _repo_find_by_visible_model_and_user(
        self,
        db: AsyncSession,
        model_id: str,
        *,
        user_id: uuid.UUID,
    ) -> ModelSetting | None:
        rows = await self._repo_find_all_by_user(db, user_id)
        return next((row for row in rows if _resolved_provider_model_id(row) == model_id), None)

    async def _repo_find_all_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        provider: str | None = None,
        config_type: str | None = None,
    ) -> list[ModelSetting]:
        if hasattr(self._repo, "find_all_by_user"):
            return await self._repo.find_all_by_user(
                db,
                user_id,
                provider=provider,
                config_type=config_type,
            )
        return await self._repo.list_by_user(
            db,
            user_id,
            provider=provider,
            config_type=config_type,
        )

    async def _repo_find_all_system_models(self, db: AsyncSession) -> list[ModelSetting]:
        if hasattr(self._repo, "find_all_system_models"):
            return await self._repo.find_all_system_models(db)
        return await self._repo.list_system(db)

    async def _repo_find_system_by_model_id(
        self,
        db: AsyncSession,
        model_id: str,
    ) -> ModelSetting | None:
        if hasattr(self._repo, "get_system_by_model"):
            return await self._repo.get_system_by_model(db, model_id)
        if hasattr(self._repo, "find_system_model_by_model_id"):
            return await self._repo.find_system_model_by_model_id(db, model_id)
        return None


# ---------------------------------------------------------------------------
# Standalone async helpers (DB-based)
# ---------------------------------------------------------------------------


async def get_system_model_config_from_db(db: AsyncSession, *, model_id: str) -> ModelConfig:
    """Get system model config from the database."""
    repo = ModelSettingRepository()
    if hasattr(repo, "get_system_by_model"):
        setting = await repo.get_system_by_model(db, model_id)
    elif hasattr(repo, "find_system_model_by_model_id"):
        setting = await repo.find_system_model_by_model_id(db, model_id)
    else:
        setting = None
    if not setting:
        raise ValueError(f"System LLM config not found for model: {model_id}")

    api_key = _decrypt_api_key(setting)
    if api_key is None and not _supports_keyless_execution(setting):
        raise LLMSettingUnavailableError(
            _missing_credentials_reason(setting),
            availability_status=ModelAvailabilityStatus.MISSING_CREDENTIALS,
        )

    return _build_model_config(
        setting,
        api_key=api_key,
        auth_token=None,
        credential_source=CredentialSource.SYSTEM,
    )


async def get_system_llm_config_from_db(db: AsyncSession, *, model_id: str) -> ModelConfig:
    """Backward-compatible alias for older callers/tests."""
    return await get_system_model_config_from_db(db, model_id=model_id)


def _build_model_config(
    setting: ModelSetting,
    *,
    api_key: SecretStr | None,
    auth_token: SecretStr | None,
    credential_source: CredentialSource,
    base_url: str | None = None,
    default_headers: dict[str, str] | None = None,
    runtime_product: str | None = None,
) -> ModelConfig:
    """Convert a DB ``ModelSetting`` row to a ``ModelConfig`` value object."""
    params_raw = _get_setting_params(setting)
    params = ModelParams.model_validate(params_raw) if params_raw else ModelParams()
    pricing = PricingInfo.model_validate(setting.pricing) if setting.pricing else None

    return ModelConfig(
        id=setting.id,
        model_id=_resolved_provider_model_id(setting),
        provider=_normalize_provider(setting.provider),
        api_key=api_key,
        auth_token=auth_token,
        base_url=base_url if base_url is not None else setting.base_url,
        default_headers=default_headers,
        display_name=setting.display_name,
        params=params,
        pricing=pricing,
        config_type=setting.config_type,
        credential_source=credential_source,
        provider_connection_id=getattr(setting, "provider_connection_id", None),
        runtime_product=runtime_product,
    )


def _credential_source(setting: ModelSetting) -> CredentialSource:
    """Infer how a setting authenticates execution."""
    if getattr(setting, "provider_connection_id", None) is not None:
        return CredentialSource.PROVIDER_OAUTH
    if getattr(setting, "user_id", None) is None and setting.config_type == ConfigType.SYSTEM.value:
        return CredentialSource.SYSTEM
    return CredentialSource.API_KEY


def _normalize_provider(value: Provider | str) -> Provider | str:
    """Coerce legacy lowercase provider strings into the canonical enum."""
    if isinstance(value, Provider):
        return value

    normalized = str(value).strip().lower()
    provider_map = {
        "openai": Provider.OPENAI,
        "anthropic": Provider.ANTHROPIC,
        "google": Provider.GOOGLE,
        "cerebras": Provider.CEREBRAS,
        "custom": Provider.CUSTOM,
    }
    return provider_map.get(normalized, value)


def _decrypt_api_key(setting: ModelSetting) -> SecretStr | None:
    """Decrypt and normalize a stored API key."""
    if not setting.encrypted_api_key:
        return None
    decrypted = encryption_manager.decrypt(setting.encrypted_api_key)
    if not decrypted:
        if setting.encrypted_api_key == "empty":
            return None
        if not encryption_manager.is_encrypted(setting.encrypted_api_key):
            return SecretStr(setting.encrypted_api_key)
        return None
    return SecretStr(decrypted)


def _get_setting_params(setting: ModelSetting) -> dict | None:
    """Read params/configs from new and legacy model setting shapes."""
    return getattr(setting, "params", None) or getattr(setting, "configs", None)


def _set_setting_params(setting: ModelSetting, value: dict | None) -> None:
    """Write params/configs for new and legacy model setting shapes."""
    try:
        setting.params = value
    except Exception:
        pass
    try:
        setattr(setting, "configs", value)
    except Exception:
        pass


def _supports_keyless_execution(setting: ModelSetting) -> bool:
    """Return True when provider credentials are expected outside ``api_key``."""
    params_raw = _get_setting_params(setting)
    params = ModelParams.model_validate(params_raw) if params_raw else ModelParams()
    return params.api_type == ApiType.VERTEX_AI


def _missing_credentials_reason(setting: ModelSetting) -> str:
    """Explain why a non-provider-backed model is unavailable."""
    if setting.user_id is None and setting.config_type == ConfigType.SYSTEM.value:
        return "This system model is missing server-side credentials."
    return "Add an API key for this model before selecting it."


def _supports_provider_managed_execution(
    connection: ProviderConnection,
    setting: ModelSetting,
) -> bool:
    """Return True when this provider connection can back direct model execution."""
    runtime_product = _normalized_runtime_product(getattr(connection, "product", None))
    provider = _normalized_provider_key(getattr(connection, "provider", None))
    setting_provider = _normalized_provider_key(getattr(setting, "provider", None))
    return (
        provider == "anthropic"
        and runtime_product == "claude_code"
        and setting_provider == "anthropic"
    ) or (provider == "openai" and runtime_product == "codex" and setting_provider == "openai")


def _unsupported_provider_reason(
    setting: ModelSetting,
    *,
    connection: ProviderConnection | None = None,
) -> str:
    """Explain why a provider-backed model cannot be executed."""
    if _normalized_provider_key(getattr(setting, "provider", None)) == "openai":
        return "Reconnect OpenAI/Codex OAuth to unlock Codex-backed model execution."
    if _normalized_runtime_product(getattr(connection, "product", None)) == "claude_code":
        return "Reconnect Anthropic Claude OAuth to unlock Claude Code-backed model execution."
    return f"{setting.provider} OAuth-backed model execution is not supported yet."


def _reauth_reason(connection: ProviderConnection) -> str:
    """Return a provider-specific reauthentication message."""
    if _normalized_runtime_product(getattr(connection, "product", None)) == "codex":
        return "Reconnect OpenAI/Codex OAuth to use this model."
    if _normalized_runtime_product(getattr(connection, "product", None)) == "claude_code":
        return "Reconnect Anthropic Claude OAuth to use this model."
    return "Reconnect this provider before selecting the model again."


def _managed_runtime_product(setting: ModelSetting) -> str | None:
    """Infer the runtime product for provider-managed rows."""
    if getattr(setting, "provider_connection_id", None) is None:
        return None
    entry = MANAGED_MODEL_CATALOG_BY_SETTING_ID.get(setting.model_id)
    if entry is not None:
        return entry.runtime_product
    provider = _normalize_provider(setting.provider)
    provider_key = provider.value if isinstance(provider, Provider) else str(provider)
    entry = MANAGED_MODEL_CATALOG_BY_PROVIDER_AND_ID.get(
        (provider_key, _resolved_provider_model_id(setting))
    )
    return entry.runtime_product if entry is not None else None


def _resolved_provider_model_id(setting: ModelSetting) -> str:
    """Return the provider-visible model identifier for a setting row."""
    params_raw = _get_setting_params(setting)
    params = ModelParams.model_validate(params_raw) if params_raw else ModelParams()
    return params.provider_model_id or setting.model_id


def _to_model_setting_info(
    setting: ModelSetting, *, include_key: bool = False
) -> ModelSettingInfoWithKey | ModelSettingInfo:
    """Convert database model to Pydantic model."""
    params_raw = _get_setting_params(setting)
    configs = ModelParams.model_validate(params_raw) if params_raw else None
    pricing = PricingInfo.model_validate(setting.pricing) if setting.pricing else None

    shared = dict(
        id=getattr(setting, "id", None) or uuid.uuid4(),
        model_id=_resolved_provider_model_id(setting),
        provider=setting.provider,
        base_url=setting.base_url,
        display_name=setting.display_name,
        configs=configs,
        pricing=pricing,
        config_type=setting.config_type,
        credential_source=_credential_source(setting),
        provider_connection_id=getattr(setting, "provider_connection_id", None),
        runtime_product=_managed_runtime_product(setting),
        is_managed=getattr(setting, "provider_connection_id", None) is not None,
        is_default=setting.is_default,
        is_active=setting.is_active,
        has_api_key=bool(getattr(setting, "encrypted_api_key", None)),
        created_at=setting.created_at.isoformat() if setting.created_at else "",
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
    )

    if include_key:
        return ModelSettingInfoWithKey(
            **shared,
            api_key=_decrypt_api_key(setting).get_secret_value()
            if _decrypt_api_key(setting)
            else None,
        )

    return ModelSettingInfo(**shared)


def _try_parse_uuid(value: str) -> uuid.UUID | None:
    """Best-effort UUID parsing for user/system setting IDs."""
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _normalized_provider_key(value: Provider | str | None) -> str:
    """Normalize provider values across canonical enums and lowercase storage keys."""
    normalized = _normalize_provider(value) if value is not None else value
    if isinstance(normalized, Provider):
        return normalized.value.lower()
    return str(normalized or "").strip().lower()


def _normalized_runtime_product(value: str | None) -> str:
    """Normalize runtime product values for comparisons."""
    return str(value or "").strip().lower()
