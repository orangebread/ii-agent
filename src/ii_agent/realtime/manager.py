"""SocketIOManager: connection lifecycle, event pub/sub, and message dispatch."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

import socketio
from pydantic import ValidationError

from ii_agent.agents.exceptions import ModelAuthenticationError, ModelProviderError
from ii_agent.core.db import get_db_session_local
from ii_agent.core.exceptions import ValidationError as CoreValidationError
from ii_agent.auth import jwt_handler
from ii_agent.core.container import ApplicationContainer
from ii_agent.realtime.events.app_events import ErrorCode
from ii_agent.realtime.pubsub import AsyncIOPubSub
from ii_agent.realtime.handlers.factory import CommandHandlerFactory
from ii_agent.realtime.schemas import ChatMessageRequest
from ii_agent.realtime.session_store import create_session_store
from ii_agent.sessions import SessionInfo
from ii_agent.sessions.service import SessionService
from ii_agent.settings.llm.exceptions import LLMSettingUnavailableError
from ii_agent.settings.llm.types import ModelAvailabilityStatus

logger = logging.getLogger(__name__)

session_store = create_session_store()


class SocketIOManager:
    """Manages Socket.IO connections, event pub/sub, and command dispatch.

    Owns an :class:`AsyncIOPubSub` with two global handlers:
    - Socket.IO emission — broadcasts to the session room
    - DB persistence — persists non-transient events

    Handlers receive the pubsub directly and call
    ``pubsub.publish(event)`` (events route by session_id).
    """

    def __init__(
        self,
        sio: socketio.AsyncServer,
        pubsub: AsyncIOPubSub,
        container: ApplicationContainer,
    ) -> None:
        self.sio = sio
        self.pubsub = pubsub
        self._container = container
        self.command_factory = CommandHandlerFactory(pubsub=self.pubsub, container=container)
        self.session_service: SessionService = container.session_service
        self.live_terminal_service = container.live_terminal_service
        self.live_terminal_service.bind_socketio(self.sio)

    async def init(self) -> None:
        await self.command_factory.initialize()
        self.sio.event(self.connect)
        self.sio.event(self.disconnect)
        self.sio.on("join_session")(self.join_session)
        self.sio.on("chat_message")(self.chat_message)
        self.sio.on("leave_session")(self.leave_session)
        self.sio.on("pty_create")(self.pty_create)
        self.sio.on("pty_input")(self.pty_input)
        self.sio.on("pty_resize")(self.pty_resize)
        self.sio.on("pty_close")(self.pty_close)

    async def shutdown(self) -> None:
        await self.live_terminal_service.shutdown()
        await self.sio.shutdown()

    async def chat_message(self, sid: str, data: Dict[str, Any]) -> None:
        # ── Validate envelope ────────────────────────────────────────────
        try:
            request = ChatMessageRequest.model_validate(data)
        except ValidationError as exc:
            logger.warning("Invalid chat_message envelope from %s: %s", sid, exc.errors())
            await self._emit_error(
                sid,
                f"Invalid message format: {exc.errors()}",
                error_code=ErrorCode.VALIDATION_ERROR,
            )
            return

        # ── Auth & session checks ────────────────────────────────────────
        session_data = await self.sio.get_session(sid)
        user_id = session_data.get("user_id") if session_data else None

        session = await self._require_session(request.session_uuid)

        if not session:
            await self._emit_error(
                sid,
                "Chat Session is required!",
                error_code=ErrorCode.SESSION_NOT_FOUND,
            )
            return

        if not user_id or not self._is_session_owner(user_id, session):
            await self._emit_error(
                sid,
                "Access denied: only the session owner can send messages",
                error_code=ErrorCode.AUTH_ERROR,
            )
            return

        command = request.content.command
        try:
            handler = self.command_factory.get_handler_by_string(command)
            if handler:
                await handler.handle(request.content, session)
            else:
                await self._emit_error(
                    sid,
                    f"Unknown command: {command}",
                    error_code=ErrorCode.VALIDATION_ERROR,
                )
        except Exception as e:
            logger.exception("Error handling chat message: %s", e)
            error_code, message = self._classify_error(e)
            await self._emit_error(sid, message, error_code=error_code)

    async def connect(self, sid: str, environ: Dict, auth: Dict | None) -> bool:
        if not auth or "token" not in auth:
            return False
        try:
            payload = jwt_handler.verify_access_token(auth["token"])
            if not payload:
                return False
            await self.sio.save_session(
                sid,
                {
                    "user_id": uuid.UUID(payload["user_id"]),
                    "session_uuid": auth.get("session_uuid"),
                    "authenticated": True,
                },
            )
            return True
        except Exception:
            logger.exception("Connection rejected: token verification failed")
            return False

    async def join_session(self, sid: str, data: Dict[str, Any]) -> None:
        session_data = await self.sio.get_session(sid)
        if not session_data or not session_data.get("authenticated"):
            await self.sio.disconnect(sid)
            return

        user_id = session_data.get("user_id")
        session_uuid_str = data.get("session_uuid") if data else None

        session_uuid: uuid.UUID | None = None
        if session_uuid_str:
            try:
                session_uuid = uuid.UUID(session_uuid_str)
            except ValueError:
                await self._emit_error(sid, "Invalid session UUID format")
                return

        try:
            async with get_db_session_local() as db:
                session_info: SessionInfo = await self.session_service.get_or_create_session(
                    db,
                    session_uuid=session_uuid,
                    user_id=user_id,
                    api_version="v1",
                )

            if not self._is_session_owner(user_id, session_info) and not session_info.is_public:
                await self._emit_error(sid, "Access denied")
                return

            await self._emit_system(
                sid,
                "Session created",
                session_id=str(session_info.id),
                is_owner=self._is_session_owner(user_id, session_info),
            )

            session_id_str = str(session_info.id)

            old_session_id = session_data.get("session_id")
            if old_session_id and old_session_id != session_id_str:
                await self.live_terminal_service.close_terminal(sid, emit_event=False)
                await self._leave_current_session(sid, old_session_id)

            await self.sio.enter_room(sid, session_id_str)
            await session_store.add_sid_to_session(session_id_str, sid)

            session_data["session_id"] = session_id_str
            await self.sio.save_session(sid, session_data)
        except Exception:
            logger.exception("Error initializing session")
            await self._emit_error(sid, "Session initialization failed")
            await self.sio.disconnect(sid)

    async def leave_session(self, sid: str, data: Dict[str, Any]) -> None:
        session_data = await self.sio.get_session(sid)
        session_id = session_data.get("session_id") if session_data else None
        await self.live_terminal_service.close_terminal(sid, emit_event=False)
        if session_id:
            await self._leave_current_session(sid, session_id)

    async def disconnect(self, sid: str) -> None:
        session_data = await self.sio.get_session(sid)
        session_id = session_data.get("session_id") if session_data else None
        await self.live_terminal_service.close_terminal(sid, emit_event=False)
        if session_id:
            await self._leave_current_session(sid, session_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_session_owner(self, user_id: uuid.UUID, session: SessionInfo) -> bool:
        return session.user_id == user_id

    async def _get_bound_session(
        self, sid: str
    ) -> tuple[Dict[str, Any] | None, SessionInfo | None]:
        session_data = await self.sio.get_session(sid)
        if not session_data or not session_data.get("authenticated"):
            return session_data, None

        session_id = session_data.get("session_id")
        if not session_id:
            return session_data, None

        try:
            return session_data, await self._require_session(uuid.UUID(session_id))
        except ValueError:
            return session_data, None

    async def _leave_current_session(self, sid: str, session_id: str) -> None:
        try:
            await self.sio.leave_room(sid, session_id)
        except Exception:
            pass
        await session_store.remove_sid_from_session(session_id, sid)

    async def _require_session(self, session_uuid: uuid.UUID) -> SessionInfo | None:
        try:
            async with get_db_session_local() as db:
                return await self.session_service.find_session_by_id(db, session_uuid)
        except ValueError:
            return None

    def _classify_error(self, exc: Exception) -> tuple[ErrorCode, str]:
        """Map uncaught realtime exceptions to stable frontend error codes."""
        if isinstance(exc, (ValidationError, CoreValidationError)):
            return ErrorCode.VALIDATION_ERROR, str(exc)

        if isinstance(exc, LLMSettingUnavailableError):
            if exc.availability_status == ModelAvailabilityStatus.MISSING_CREDENTIALS:
                return ErrorCode.MISSING_CREDENTIALS, str(exc)
            return ErrorCode.PROVIDER_CONFIG_ERROR, str(exc)

        if isinstance(exc, ModelAuthenticationError):
            return ErrorCode.PROVIDER_CONFIG_ERROR, str(exc)

        if isinstance(exc, ModelProviderError):
            message = str(exc)
            lowered = message.lower()
            if "instructions are required" in lowered or "store must be set to false" in lowered:
                return ErrorCode.PROVIDER_CONTRACT_ERROR, message
            return ErrorCode.EXECUTION_ERROR, message

        return ErrorCode.INTERNAL_ERROR, "Error processing message"

    async def _emit_error(
        self,
        sid: str,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    ) -> None:
        """Emit an error directly to a socket (pre-session or auth errors)."""
        await self.sio.emit(
            "chat_event",
            {
                "group": "system",
                "name": "system.error",
                "error_code": error_code.value,
                "detail": message,
                "content": {"message": message, "error_code": error_code.value},
            },
            to=sid,
        )

    async def _emit_terminal_error(
        self,
        sid: str,
        message: str,
        *,
        terminal_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"message": message}
        if terminal_id:
            payload["terminal_id"] = terminal_id
        await self.sio.emit("pty_error", payload, to=sid)

    async def _emit_system(self, sid: str, message: str, **kwargs: Any) -> None:
        """Emit a system message directly to a socket."""
        payload = {
            "group": "connection",
            "name": "connection.established",
            "content": {"message": message, **kwargs},
        }
        await self.sio.emit("chat_event", payload, to=sid)

    async def pty_create(self, sid: str, data: Dict[str, Any] | None) -> None:
        payload = data or {}
        terminal_id = payload.get("terminal_id")
        if not isinstance(terminal_id, str) or not terminal_id:
            await self._emit_terminal_error(sid, "Missing terminal id")
            return

        session_data, session = await self._get_bound_session(sid)
        user_id = session_data.get("user_id") if session_data else None
        if not session or not user_id or not self._is_session_owner(user_id, session):
            await self._emit_terminal_error(
                sid,
                "Terminal session is not ready",
                terminal_id=terminal_id,
            )
            return

        cols = payload.get("cols")
        rows = payload.get("rows")
        await self.live_terminal_service.create_terminal(
            sid,
            session_info=session,
            terminal_id=terminal_id,
            cols=cols if isinstance(cols, int) else None,
            rows=rows if isinstance(rows, int) else None,
        )

    async def pty_input(self, sid: str, data: Dict[str, Any] | None) -> None:
        payload = data or {}
        terminal_id = payload.get("terminal_id")
        text = payload.get("data")
        if not isinstance(terminal_id, str) or not terminal_id or not isinstance(text, str):
            return

        await self.live_terminal_service.write_input(
            sid,
            terminal_id=terminal_id,
            data=text,
        )

    async def pty_resize(self, sid: str, data: Dict[str, Any] | None) -> None:
        payload = data or {}
        terminal_id = payload.get("terminal_id")
        if not isinstance(terminal_id, str) or not terminal_id:
            return

        cols = payload.get("cols")
        rows = payload.get("rows")
        await self.live_terminal_service.resize_terminal(
            sid,
            terminal_id=terminal_id,
            cols=cols if isinstance(cols, int) else None,
            rows=rows if isinstance(rows, int) else None,
        )

    async def pty_close(self, sid: str, data: Dict[str, Any] | None) -> None:
        payload = data or {}
        terminal_id = payload.get("terminal_id")
        await self.live_terminal_service.close_terminal(
            sid,
            terminal_id=terminal_id if isinstance(terminal_id, str) and terminal_id else None,
        )
