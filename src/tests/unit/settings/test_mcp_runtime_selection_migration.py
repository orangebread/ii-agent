from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


_MIGRATION_PATH = Path(
    "/Volumes/OWC Envoy Ultra/projects/_tools_/ii-agent/migrations/versions/"
    "20260416_000003_provider_connections_and_runtime_selection.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "mcp_runtime_selection_migration", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.provider_connection_inserts = []
        self.mcp_setting_updates = []
        self.user_updates = []

    def execute(self, stmt):
        if isinstance(stmt, sa.sql.Select):
            return _FakeMappingsResult(self.rows)

        params = stmt.compile(dialect=postgresql.dialect()).params
        table_name = stmt.table.name
        if stmt.is_insert and table_name == "provider_connections":
            self.provider_connection_inserts.append(params)
        elif stmt.is_update and table_name == "mcp_settings":
            self.mcp_setting_updates.append(params)
        elif stmt.is_update and table_name == "users":
            self.user_updates.append(params)
        return None


pytestmark = pytest.mark.unit


def test_backfill_provider_connections_reuses_single_connection_for_duplicate_runtime_rows(
    monkeypatch,
):
    module = _load_migration_module()
    user_id = uuid.uuid4()
    first_setting_id = uuid.uuid4()
    second_setting_id = uuid.uuid4()
    rows = [
        {
            "id": first_setting_id,
            "user_id": user_id,
            "metadata": {
                "tool_type": "codex",
                "auth_mode": "api_key",
                "auth_json": {"OPENAI_API_KEY": "newer"},
            },
            "is_active": True,
            "created_at": datetime(2026, 4, 16, tzinfo=timezone.utc),
        },
        {
            "id": second_setting_id,
            "user_id": user_id,
            "metadata": {
                "tool_type": "codex",
                "auth_mode": "api_key",
                "auth_json": {"OPENAI_API_KEY": "older"},
            },
            "is_active": False,
            "created_at": datetime(2026, 4, 15, tzinfo=timezone.utc),
        },
    ]
    fake_connection = _FakeConnection(rows)

    monkeypatch.setattr(module.op, "get_bind", lambda: fake_connection)
    monkeypatch.setattr(module.encryption_manager, "encrypt", lambda payload: f"enc:{payload}")

    module._backfill_provider_connections()

    assert len(fake_connection.provider_connection_inserts) == 1
    assert len(fake_connection.mcp_setting_updates) == 2
    provider_connection_ids = {
        update["provider_connection_id"] for update in fake_connection.mcp_setting_updates
    }
    assert len(provider_connection_ids) == 1
