"""Repository layer for users domain - data access only."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ii_agent.users.models import APIKey, User


class UserRepository:
    """Data access layer for User model."""

    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        """Get a user by their ID."""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get a user by their email (case-insensitive)."""
        result = await db.execute(select(User).where(func.lower(User.email) == email.lower()))
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        *,
        email: str,
        first_name: str = "",
        last_name: str = "",
        avatar: Optional[str] = None,
        email_verified: bool = False,
        subscription_plan: Optional[str] = None,
        login_provider: Optional[str] = None,
    ) -> User:
        """Create a new user and persist it."""
        user_kwargs: dict[str, Any] = {
            "id": uuid.uuid4(),
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "avatar": avatar,
            "role": "user",
            "is_active": True,
            "email_verified": email_verified,
            "last_login_at": datetime.now(timezone.utc),
            "login_provider": login_provider,
        }
        if subscription_plan is not None:
            user_kwargs["subscription_plan"] = subscription_plan

        user = User(**user_kwargs)
        db.add(user)
        await db.flush()
        return user

    async def update_fields(self, db: AsyncSession, user: User, **fields: Any) -> None:
        """Update arbitrary fields on a user and flush changes."""
        for key, value in fields.items():
            if value is not None:
                setattr(user, key, value)
        await db.flush()

    async def update_profile(
        self,
        db: AsyncSession,
        user: User,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        avatar: Optional[str] = None,
        email_verified: Optional[bool] = None,
        login_provider: Optional[str] = None,
    ) -> None:
        """Update user profile fields (only non-None values are applied)."""
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if avatar is not None:
            user.avatar = avatar
        if email_verified is not None:
            user.email_verified = user.email_verified or email_verified
        if login_provider is not None:
            user.login_provider = login_provider
        user.last_login_at = datetime.now(timezone.utc)
        await db.flush()

    async def set_active(self, db: AsyncSession, user: User, *, is_active: bool) -> None:
        """Activate or deactivate a user account."""
        user.is_active = is_active
        await db.flush()

    async def set_language(self, db: AsyncSession, user: User, language: str) -> None:
        """Update the user's preferred language."""
        user.language = language
        await db.flush()

    async def set_default_mcp_setting_id(
        self,
        db: AsyncSession,
        user: User,
        default_mcp_setting_id: uuid.UUID | None,
    ) -> None:
        """Set or clear the user's default MCP runtime selection."""
        user.default_mcp_setting_id = default_mcp_setting_id
        await db.flush()


class APIKeyRepository:
    """Data access layer for APIKey model."""

    async def get_active_for_user(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[str]:
        """Get the active API key string for a user.

        Returns the most recently created active API key, or None.
        """
        result = await db.execute(
            select(APIKey)
            .where(APIKey.user_id == user_id, APIKey.is_active)
            .order_by(desc(APIKey.created_at))
        )
        api_key_obj = result.scalar_one_or_none()
        return api_key_obj.api_key if api_key_obj else None

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        api_key: str,
    ) -> APIKey:
        """Create a new API key for a user."""
        key = APIKey(
            id=uuid.uuid4(),
            user_id=user_id,
            api_key=api_key,
            is_active=True,
        )
        db.add(key)
        await db.flush()
        return key
