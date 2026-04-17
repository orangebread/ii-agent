"""Business logic for users domain."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from typing import TYPE_CHECKING

from ii_agent.core.config.settings import Settings
from ii_agent.core.redis.cache import TypedEntityCache
from ii_agent.users.exceptions import UserDisabledException, WaitlistDeniedException
from ii_agent.users.models import APIKey, User
from ii_agent.users.repository import APIKeyRepository, UserRepository
from ii_agent.users.schemas import UserResponse
from ii_agent.users.waitlist_repository import WaitlistRepository

if TYPE_CHECKING:
    from ii_agent.credits.service import CreditService

# Valid language codes accepted by update_language
VALID_LANGUAGES = ("en", "vi", "hi", "ja")

KEY_PATTERN = "user:{user_id}"


class UserService:
    """Service for user operations using injected repositories."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        api_key_repo: APIKeyRepository,
        waitlist_repo: WaitlistRepository,
        credit_service: "CreditService",
        cache: TypedEntityCache[UserResponse],
        config: Settings,
    ) -> None:
        self._config = config
        self._user_repo = user_repo
        self._api_key_repo = api_key_repo
        self._waitlist_repo = waitlist_repo
        self._credit_service = credit_service
        self._cache = cache

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_user_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[UserResponse]:
        """Get a user by their ID (cached)."""
        cache_key = KEY_PATTERN.format(user_id=str(user_id))
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        user = await self._user_repo.get_by_id(db, user_id)
        if user is None:
            return None

        res = UserResponse.model_validate(user)
        await self._cache.set(cache_key, res)
        return res

    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get a user by their email."""
        return await self._user_repo.get_by_email(db, email)

    async def get_active_api_key(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[str]:
        """Get the active API key for a user."""
        return await self._api_key_repo.get_active_for_user(db, user_id)

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    async def create_user(
        self,
        db: AsyncSession,
        *,
        email: str,
        first_name: str = "",
        last_name: str = "",
        avatar: Optional[str] = None,
        email_verified: bool = False,
        bonus_credits: float = 0.0,
        login_provider: Optional[str] = None,
    ) -> User:
        """Create a new user with default settings and an API key.

        This is the single entry-point for user creation. It:
        1. Persists the User row with default credits / plan from config.
        2. Generates and persists an API key for the new user.
        """
        user = await self._user_repo.create(
            db,
            email=email,
            first_name=first_name,
            last_name=last_name,
            avatar=avatar,
            email_verified=email_verified,
            login_provider=login_provider,
        )
        await self.create_api_key(db, user_id=user.id)
        # Create credit_balances row + initial_balance ledger entry atomically.
        await self._credit_service.ensure_balance_exists(
            db,
            user.id,
            credits=self._config.credits.default_user_credits,
            bonus_credits=bonus_credits,
        )
        return user

    async def create_api_key(self, db: AsyncSession, *, user_id: uuid.UUID) -> APIKey:
        """Generate and persist a new prefixed API key for *user_id*."""
        from ii_agent.auth.utils import generate_prefixed_api_key

        return await self._api_key_repo.create(
            db,
            user_id=user_id,
            api_key=generate_prefixed_api_key(),
        )

    async def update_login_profile(
        self,
        db: AsyncSession,
        user: User,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        avatar: Optional[str] = None,
        email_verified: Optional[bool] = None,
        login_provider: Optional[str] = None,
    ) -> User:
        """Update profile fields on an existing user during login."""
        await self._user_repo.update_profile(
            db,
            user,
            first_name=first_name,
            last_name=last_name,
            avatar=avatar,
            email_verified=email_verified,
            login_provider=login_provider,
        )
        await self._cache.evict(KEY_PATTERN.format(user_id=str(user.id)))
        return user

    # ------------------------------------------------------------------
    # OAuth user resolution
    # ------------------------------------------------------------------

    async def check_waitlist(self, db: AsyncSession, email: str) -> None:
        """Raise if waitlist is enabled and *email* is not on the waitlist.

        Internal ``@ii.inc`` addresses are always allowed.

        Raises:
            WaitlistDeniedException: If the email is not on the waitlist.
        """
        if not self._config.credits.waitlist_enabled:
            return
        if email.endswith("@ii.inc"):
            return

        entry = await self._waitlist_repo.get_by_email(db, email)
        if entry is None:
            raise WaitlistDeniedException(
                "Thank you for your interest. We're currently in private beta and expanding access soon."
            )

    async def find_or_create_oauth_user(
        self,
        db: AsyncSession,
        *,
        email: str,
        first_name: str = "",
        last_name: str = "",
        avatar: Optional[str] = None,
        email_verified: bool = False,
        bonus_credits: float = 0.0,
        login_provider: Optional[str] = None,
    ) -> User:
        """Look up an existing user by *email* or create a new one.

        For returning users the profile is updated with the latest OAuth info.

        Raises:
            UserDisabledException: If the user account is disabled.
        """
        user = await self._user_repo.get_by_email(db, email)

        if user and not user.is_active:
            raise UserDisabledException("User account is disabled")

        if not user:
            user = await self.create_user(
                db,
                email=email,
                first_name=first_name,
                last_name=last_name,
                avatar=avatar,
                email_verified=email_verified,
                bonus_credits=bonus_credits,
                login_provider=login_provider,
            )
        else:
            user = await self.update_login_profile(
                db,
                user,
                first_name=first_name,
                last_name=last_name,
                avatar=avatar,
                email_verified=email_verified,
                login_provider=login_provider,
            )

        return user

    # ------------------------------------------------------------------
    # Profile mutations
    # ------------------------------------------------------------------

    async def update_language(self, db: AsyncSession, user: User, language: str) -> None:
        """Update a user's preferred language.

        Raises ``ValueError`` if *language* is not in the allowed set.
        """
        if language not in VALID_LANGUAGES:
            from ii_agent.core.exceptions import ValidationError

            raise ValidationError(
                f"Invalid language. Supported languages: {', '.join(VALID_LANGUAGES)}"
            )
        await self._user_repo.set_language(db, user, language)
        await self._cache.evict(KEY_PATTERN.format(user_id=str(user.id)))

    async def set_default_mcp_setting_id(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        default_mcp_setting_id: uuid.UUID | None,
    ) -> None:
        """Persist the user's default MCP runtime selection."""
        user = await self._user_repo.get_by_id(db, user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        await self._user_repo.set_default_mcp_setting_id(db, user, default_mcp_setting_id)
        await self._cache.evict(KEY_PATTERN.format(user_id=str(user.id)))

    async def delete_user(self, db: AsyncSession, user: User) -> None:
        """Soft-delete a user account by deactivating it."""
        await self._user_repo.set_active(db, user, is_active=False)
        await self._cache.evict(KEY_PATTERN.format(user_id=str(user.id)))
