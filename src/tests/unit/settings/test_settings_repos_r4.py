"""Unit tests for LLM/MCP repositories, stores, and routers (r4)."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# LLMSettingRepository
# ---------------------------------------------------------------------------


class TestLLMSettingRepositoryR4:
    def _make_repo(self):
        from ii_agent.settings.llm.repository import ModelSettingRepository

        return ModelSettingRepository()

    @pytest.mark.asyncio
    async def test_get_by_id_and_user_returns_setting(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_setting = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_setting
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.find_by_id_and_user_id(mock_db, "setting-1", "user-1")
        assert result is mock_setting

    @pytest.mark.asyncio
    async def test_get_by_id_and_user_returns_none_when_not_found(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.find_by_id_and_user_id(mock_db, "missing", "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_model_and_user_returns_setting(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_setting = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_setting
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.find_by_model_and_user(mock_db, "gpt-4", "user-1")
        assert result is mock_setting

    @pytest.mark.asyncio
    async def test_get_by_model_and_user_returns_none(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.find_by_model_and_user(mock_db, "nonexistent-model", "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_user_returns_settings_list(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_settings = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_settings
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.find_all_by_user(mock_db, "user-1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_by_user_with_provider_filter(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.find_all_by_user(mock_db, "user-1", provider="openai")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_delete_removes_setting(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_setting = MagicMock()
        await repo.delete(mock_db, mock_setting)
        mock_db.delete.assert_called_once_with(mock_setting)
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_persists_setting_via_base_repository(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_setting = MagicMock()

        result = await repo.create(mock_db, mock_setting)

        assert result is mock_setting
        mock_db.add.assert_called_once_with(mock_setting)
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(mock_setting)


# ---------------------------------------------------------------------------
# MCPSettingRepository
# ---------------------------------------------------------------------------


class TestMCPSettingRepositoryR4:
    def _make_repo(self):
        from ii_agent.settings.mcp.repository import MCPSettingRepository

        return MCPSettingRepository()

    @pytest.mark.asyncio
    async def test_get_by_id_and_user_returns_setting(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_setting = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_setting
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.get_by_id_and_user(mock_db, "setting-1", "user-1")
        assert result is mock_setting

    @pytest.mark.asyncio
    async def test_get_by_id_and_user_returns_none(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.get_by_id_and_user(mock_db, "missing", "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_user_and_tool_type_returns_setting(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_setting = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_setting
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.get_by_user_and_tool_type(mock_db, "user-1", "codex")
        assert result is mock_setting

    @pytest.mark.asyncio
    async def test_list_by_user_returns_list(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_settings = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_settings
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.list_by_user(mock_db, "user-1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_by_user_only_active_filter(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.list_by_user(mock_db, "user-1", only_active=True)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_by_user_no_metadata_filter(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.list_by_user(mock_db, "user-1", no_metadata=True)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_active_by_user_delegates_correctly(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [MagicMock()]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await repo.list_active_by_user(mock_db, "user-1")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_delete_removes_setting(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_setting = MagicMock()
        await repo.delete(mock_db, mock_setting)
        mock_db.delete.assert_called_once_with(mock_setting)
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_persists_setting_via_base_repository(self):
        repo = self._make_repo()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_setting = MagicMock()

        result = await repo.create(mock_db, mock_setting)

        assert result is mock_setting
        mock_db.add.assert_called_once_with(mock_setting)
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(mock_setting)


# ---------------------------------------------------------------------------
# FileSettingsStore
# ---------------------------------------------------------------------------


class TestFileSettingsStoreR4:
    @pytest.mark.asyncio
    async def test_load_returns_none_when_file_not_found(self):
        from ii_agent.settings.llm.store.file_settings_store import FileSettingsStore

        mock_storage = MagicMock()
        mock_storage.read = MagicMock(side_effect=FileNotFoundError("not found"))
        store = FileSettingsStore(file_store=mock_storage, path="settings.json")
        result = await store.load()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_returns_persisted_settings(self):
        from ii_agent.settings.llm.store.file_settings_store import FileSettingsStore
        from ii_agent.settings.llm.persisted_settings import PersistedSettings

        data = PersistedSettings()
        json_str = data.model_dump_json(context={"expose_secrets": True})
        mock_storage = MagicMock()
        mock_storage.read = MagicMock(return_value=io.BytesIO(json_str.encode("utf-8")))
        store = FileSettingsStore(file_store=mock_storage, path="settings.json")
        result = await store.load()
        assert result is not None
        assert isinstance(result, PersistedSettings)

    @pytest.mark.asyncio
    async def test_store_writes_json_to_storage(self):
        from ii_agent.settings.llm.store.file_settings_store import FileSettingsStore
        from ii_agent.settings.llm.persisted_settings import PersistedSettings

        mock_storage = MagicMock()
        mock_storage.write = MagicMock()
        store = FileSettingsStore(file_store=mock_storage, path="settings.json")
        settings = PersistedSettings()
        await store.store(settings)
        mock_storage.write.assert_called_once()
        call_args = mock_storage.write.call_args
        content_arg = call_args[0][0]
        path_arg = call_args[0][1]
        assert path_arg == "settings.json"
        # Content should be a BytesIO-like object
        assert hasattr(content_arg, "read")

    @pytest.mark.asyncio
    async def test_get_instance_returns_store(self):
        from ii_agent.settings.llm.store.file_settings_store import FileSettingsStore

        with patch("ii_agent.settings.llm.store.file_settings_store.default_storage"):
            store = await FileSettingsStore.get_instance(config=MagicMock(), user_id="user-1")
        assert isinstance(store, FileSettingsStore)

    @pytest.mark.asyncio
    async def test_get_instance_no_user_id(self):
        from ii_agent.settings.llm.store.file_settings_store import FileSettingsStore

        with patch("ii_agent.settings.llm.store.file_settings_store.default_storage"):
            store = await FileSettingsStore.get_instance(config=MagicMock(), user_id=None)
        assert isinstance(store, FileSettingsStore)

    @pytest.mark.asyncio
    async def test_call_sync_from_async_runs_function(self):
        from ii_agent.settings.llm.store.file_settings_store import call_sync_from_async

        result = await call_sync_from_async(lambda x: x * 2, 5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_call_sync_from_async_with_exception(self):
        from ii_agent.settings.llm.store.file_settings_store import call_sync_from_async

        with pytest.raises(ValueError, match="test error"):
            await call_sync_from_async(lambda: (_ for _ in ()).throw(ValueError("test error")))


# ---------------------------------------------------------------------------
# MCP schema tests
# ---------------------------------------------------------------------------


class TestMCPSchemasR4:
    def test_validate_metadata_codex(self):
        from ii_agent.settings.mcp.schemas import validate_metadata, CodexMetadata

        metadata = {"tool_type": "codex", "auth_json": {"token": "abc"}}
        result = validate_metadata(metadata)
        assert isinstance(result, CodexMetadata)
        assert result.tool_type == "codex"

    def test_validate_metadata_codex_with_json_string(self):
        from ii_agent.settings.mcp.schemas import validate_metadata, CodexMetadata

        metadata = {"tool_type": "codex", "auth_json": '{"token": "abc"}'}
        result = validate_metadata(metadata)
        assert isinstance(result, CodexMetadata)
        assert result.auth_json == {"token": "abc"}

    def test_validate_metadata_codex_invalid_json_raises(self):
        from ii_agent.settings.mcp.schemas import validate_metadata

        metadata = {"tool_type": "codex", "auth_json": "not-valid-json{"}
        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_metadata(metadata)

    def test_validate_metadata_claude_code(self):
        from ii_agent.settings.mcp.schemas import validate_metadata, ClaudeCodeMetadata

        metadata = {
            "tool_type": "claude_code",
            "auth_json": {"access_token": "token", "refresh_token": "rt", "expires_at": 9999},
        }
        result = validate_metadata(metadata)
        assert isinstance(result, ClaudeCodeMetadata)
        assert not hasattr(result, "auth_json")

    def test_validate_metadata_composio(self):
        from ii_agent.settings.mcp.schemas import validate_metadata, ComposioMetadata

        metadata = {
            "tool_type": "composio",
            "toolkit_slug": "gmail",
            "toolkit_name": "Gmail",
            "profile_id": "11111111-1111-1111-1111-111111111111",
        }
        result = validate_metadata(metadata)
        assert isinstance(result, ComposioMetadata)

    def test_validate_metadata_unknown_type_returns_base(self):
        from ii_agent.settings.mcp.schemas import validate_metadata, MCPMetadata

        metadata = {"tool_type": "some_custom_type"}
        result = validate_metadata(metadata)
        assert isinstance(result, MCPMetadata)
        assert result.tool_type == "some_custom_type"

    def test_validate_metadata_empty_raises(self):
        from ii_agent.settings.mcp.schemas import validate_metadata

        with pytest.raises(ValueError, match="cannot be empty"):
            validate_metadata({})

    def test_validate_metadata_none_raises(self):
        from ii_agent.settings.mcp.schemas import validate_metadata

        with pytest.raises(ValueError, match="cannot be empty"):
            validate_metadata(None)  # type: ignore

    def test_mcp_setting_list_get_combined_active_config(self):
        from ii_agent.settings.mcp.schemas import MCPSettingList, MCPSettingInfo, MCPServersConfig

        setting = MagicMock(spec=MCPSettingInfo)
        setting.id = "s-1"
        setting.is_active = True
        setting.mcp_config = MCPServersConfig(mcpServers={})
        setting.metadata = None
        lst = MCPSettingList(settings=[setting])
        combined = lst.get_combined_active_config()
        assert isinstance(combined, MCPServersConfig)

    def test_mcp_setting_list_skips_codex_as_mcp(self):
        from ii_agent.settings.mcp.schemas import MCPSettingList, MCPSettingInfo, MCPServersConfig
        from fastmcp.mcp_config import RemoteMCPServer

        setting = MagicMock(spec=MCPSettingInfo)
        setting.id = "s-1"
        setting.is_active = True
        mock_server = MagicMock(spec=RemoteMCPServer)
        setting.mcp_config = MCPServersConfig(mcpServers={"codex-as-mcp": mock_server})
        setting.metadata = None
        lst = MCPSettingList(settings=[setting])
        combined = lst.get_combined_active_config()
        # codex-as-mcp should be skipped
        assert "codex-as-mcp" not in combined.mcpServers

    def test_mcp_setting_list_get_by_id(self):
        from ii_agent.settings.mcp.schemas import MCPSettingList, MCPSettingInfo

        setting = MagicMock(spec=MCPSettingInfo)
        setting.id = "target-id"
        lst = MCPSettingList(settings=[setting])
        result = lst.get_by_id("target-id")
        assert result is setting

    def test_mcp_setting_list_get_by_id_returns_none_when_missing(self):
        from ii_agent.settings.mcp.schemas import MCPSettingList

        lst = MCPSettingList(settings=[])
        result = lst.get_by_id("missing")
        assert result is None


# ---------------------------------------------------------------------------
# LLM schema tests
# ---------------------------------------------------------------------------


class TestLLMSchemasR4:
    def test_model_setting_info_with_key_to_llm_config(self):
        from ii_agent.settings.llm.schemas import ModelSettingInfoWithKey, ModelParams
        from ii_agent.core.config.llm_config import LLMConfig

        info = ModelSettingInfoWithKey(
            id="setting-1",
            model_id="gpt-4",
            provider="openai",
            base_url=None,
            display_name=None,
            configs=ModelParams(
                max_retries=3, max_message_chars=10000, temperature=0.0, thinking_tokens=0
            ),
            pricing=None,
            config_type="user",
            is_default=True,
            has_api_key=True,
            created_at="2024-01-01T00:00:00Z",
            api_key="sk-test-key",
        )
        config = info.to_llm_config()
        assert isinstance(config, LLMConfig)
        assert config.model == "gpt-4"

    def test_model_setting_info_with_key_no_api_key_raises(self):
        from ii_agent.settings.llm.schemas import ModelSettingInfoWithKey, ModelParams

        info = ModelSettingInfoWithKey(
            id="setting-1",
            model_id="gpt-4",
            provider="openai",
            base_url=None,
            display_name=None,
            configs=ModelParams(
                max_retries=3, max_message_chars=10000, temperature=0.0, thinking_tokens=0
            ),
            pricing=None,
            config_type="user",
            is_default=True,
            has_api_key=False,
            created_at="2024-01-01T00:00:00Z",
            api_key=None,
        )
        with pytest.raises(ValueError, match="API key is required"):
            info.to_llm_config()

    def test_model_setting_list_get_by_id(self):
        from ii_agent.settings.llm.schemas import ModelSettingList, ModelSettingInfo

        info = MagicMock(spec=ModelSettingInfo)
        info.id = "setting-1"
        lst = ModelSettingList(models=[info])
        result = lst.get_by_id("setting-1")
        assert result is info

    def test_model_setting_list_get_by_id_missing_returns_none(self):
        from ii_agent.settings.llm.schemas import ModelSettingList

        lst = ModelSettingList(models=[])
        assert lst.get_by_id("missing") is None

    def test_model_setting_list_get_by_model(self):
        from ii_agent.settings.llm.schemas import ModelSettingList, ModelSettingInfo

        info = MagicMock(spec=ModelSettingInfo)
        info.model_id = "gpt-4"
        lst = ModelSettingList(models=[info])
        result = lst.get_by_model("gpt-4")
        assert result is info

    def test_model_setting_info_with_key_with_azure_configs(self):
        from ii_agent.settings.llm.schemas import ModelSettingInfoWithKey, ModelParams

        # Azure-specific settings are now stored in configs JSONB
        info = ModelSettingInfoWithKey(
            id="setting-1",
            model_id="gpt-4",
            provider="custom",
            base_url=None,
            display_name=None,
            configs=ModelParams(
                max_retries=3,
                max_message_chars=10000,
                temperature=0.0,
                thinking_tokens=0,
                azure_endpoint="https://myazure.openai.azure.com",
                azure_api_version="2024-02-01",
            ),
            pricing=None,
            config_type="user",
            is_default=True,
            has_api_key=True,
            created_at="2024-01-01T00:00:00Z",
            api_key="sk-azure-key",
        )
        config = info.to_llm_config()
        assert config.azure_endpoint == "https://myazure.openai.azure.com"
        assert config.azure_api_version == "2024-02-01"
