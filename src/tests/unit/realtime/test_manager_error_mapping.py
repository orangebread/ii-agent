from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ii_agent.agents.exceptions import ModelProviderError
from ii_agent.realtime.events.app_events import ErrorCode
from ii_agent.realtime.manager import SocketIOManager


class _FakeSio:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, object]] = {}
        self.emitted: list[tuple[str, dict[str, object], str | None]] = []

    async def get_session(self, sid: str) -> dict[str, object] | None:
        return self.sessions.get(sid)

    async def emit(self, event: str, payload: dict[str, object], to: str | None = None) -> None:
        self.emitted.append((event, payload, to))


def _make_manager(sio: _FakeSio, *, factory: MagicMock | None = None) -> SocketIOManager:
    container = SimpleNamespace(
        session_service=MagicMock(),
        live_terminal_service=SimpleNamespace(bind_socketio=MagicMock()),
    )
    with patch(
        "ii_agent.realtime.manager.CommandHandlerFactory",
        return_value=factory or MagicMock(),
    ):
        return SocketIOManager(
            sio=sio,
            pubsub=MagicMock(),
            container=container,
        )


def test_classify_error_maps_provider_contract_failures():
    manager = _make_manager(_FakeSio())

    error_code, message = manager._classify_error(ModelProviderError("Store must be set to false"))

    assert error_code == ErrorCode.PROVIDER_CONTRACT_ERROR
    assert message == "Store must be set to false"


@pytest.mark.asyncio
async def test_chat_message_emits_structured_provider_contract_error():
    sio = _FakeSio()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    sio.sessions["sid-1"] = {"user_id": user_id}

    handler = SimpleNamespace(
        handle=AsyncMock(side_effect=ModelProviderError("Instructions are required"))
    )
    factory = MagicMock()
    factory.get_handler_by_string.return_value = handler
    manager = _make_manager(sio, factory=factory)

    with patch.object(
        manager,
        "_require_session",
        new=AsyncMock(
            return_value=SimpleNamespace(id=session_id, user_id=user_id, is_public=False)
        ),
    ):
        await manager.chat_message(
            "sid-1",
            {
                "session_uuid": str(session_id),
                "content": {"command": "ping"},
            },
        )

    assert len(sio.emitted) == 1
    event_name, payload, target_sid = sio.emitted[0]
    assert event_name == "chat_event"
    assert target_sid == "sid-1"
    assert payload["name"] == "system.error"
    assert payload["content"]["error_code"] == "provider_contract_error"
    assert payload["content"]["message"] == "Instructions are required"
