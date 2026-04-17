from __future__ import annotations

import uuid

import pytest

from ii_agent.settings.provider_connections.service import ProviderConnectionService


class FakeProviderConnectionRepo:
    def __init__(self):
        self.by_id = {}
        self.by_key = {}

    async def list_by_user(self, db, *, user_id):
        return [row for row in self.by_id.values() if row.user_id == user_id]

    async def get_by_id_and_user(self, db, connection_id, user_id):
        row = self.by_id.get(str(connection_id))
        if row and row.user_id == user_id:
            return row
        return None

    async def get_by_provider_product(self, db, *, user_id, provider, product):
        return self.by_key.get((str(user_id), provider, product))

    async def create(self, db, row):
        self.by_id[str(row.id)] = row
        self.by_key[(str(row.user_id), row.provider, row.product)] = row
        return row

    async def update(self, db, row):
        self.by_id[str(row.id)] = row
        self.by_key[(str(row.user_id), row.provider, row.product)] = row
        return row


@pytest.mark.asyncio
async def test_upsert_connection_encrypts_and_lists():
    repo = FakeProviderConnectionRepo()
    service = ProviderConnectionService(repo=repo)
    user_id = uuid.uuid4()

    created = await service.upsert_connection(
        db=None,
        user_id=user_id,
        provider="openai",
        product="codex",
        credentials={"OPENAI_API_KEY": "sk-test"},
        auth_mode="api_key",
        display_name="Codex",
    )

    assert created.id

    listed = await service.list_connections(db=None, user_id=user_id)
    assert len(listed.connections) == 1
    assert listed.connections[0].provider == "openai"
    assert listed.connections[0].product == "codex"

    decrypted = service.get_credentials_dict(created)
    assert decrypted["OPENAI_API_KEY"] == "sk-test"


@pytest.mark.asyncio
async def test_upsert_connection_updates_existing_row():
    repo = FakeProviderConnectionRepo()
    service = ProviderConnectionService(repo=repo)
    user_id = uuid.uuid4()

    created = await service.upsert_connection(
        db=None,
        user_id=user_id,
        provider="anthropic",
        product="claude_code",
        credentials={"claudeAiOauth": {"refreshToken": "first"}},
        auth_mode="anthropic_oauth",
        display_name="Claude Code",
    )

    updated = await service.upsert_connection(
        db=None,
        user_id=user_id,
        provider="anthropic",
        product="claude_code",
        credentials={"claudeAiOauth": {"refreshToken": "second"}},
        auth_mode="anthropic_oauth",
        display_name="Claude Code",
    )

    assert updated.id == created.id
    decrypted = service.get_credentials_dict(updated)
    assert decrypted["claudeAiOauth"]["refreshToken"] == "second"
