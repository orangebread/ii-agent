from uuid import UUID

from ii_agent.settings.mcp.schemas import (
    ClaudeCodeMetadata,
    CodexMetadata,
    ComposioMetadata,
    MCPMetadata,
    MCPServersConfig,
    MCPSettingInfo,
    MCPSettingList,
    validate_metadata,
)
import pytest


def _stdio_server(command: str) -> dict:
    return {"command": command, "args": ["-y", "pkg"]}


def _remote_server(url: str) -> dict:
    return {"url": url, "type": "remote"}


def _setting(
    setting_id: str,
    *,
    is_active: bool,
    servers: dict,
    metadata=None,
) -> MCPSettingInfo:
    return MCPSettingInfo(
        id=setting_id,
        mcp_config=MCPServersConfig.model_validate({"mcpServers": servers}),
        metadata=metadata,
        is_active=is_active,
        created_at="2026-02-25T00:00:00Z",
    )


def test_validate_metadata_rejects_empty_input():
    with pytest.raises(ValueError, match="Metadata cannot be empty"):
        validate_metadata({})


def test_validate_metadata_parses_codex_auth_json_string():
    metadata = validate_metadata(
        {
            "tool_type": "codex",
            "auth_json": '{"OPENAI_API_KEY": "k"}',
            "store_path": "~/.codex",
        }
    )

    assert isinstance(metadata, CodexMetadata)
    assert metadata.auth_json == {"OPENAI_API_KEY": "k"}


def test_validate_metadata_rejects_invalid_codex_auth_json_string():
    with pytest.raises(ValueError, match="Invalid JSON in auth_json"):
        validate_metadata(
            {
                "tool_type": "codex",
                "auth_json": "{bad-json}",
                "store_path": "~/.codex",
            }
        )


def test_validate_metadata_ignores_legacy_claude_code_auth_json():
    metadata = validate_metadata(
        {
            "tool_type": "claude_code",
            "auth_json": '{"access_token": "a", "refresh_token": "r"}',
            "store_path": "~/.claude",
        }
    )

    assert isinstance(metadata, ClaudeCodeMetadata)
    assert metadata.store_path == "~/.claude"
    assert not hasattr(metadata, "auth_json")


def test_validate_metadata_handles_composio_and_unknown_types():
    composio = validate_metadata(
        {
            "tool_type": "composio",
            "toolkit_slug": "gmail",
            "toolkit_name": "Gmail",
            "profile_id": "11111111-1111-1111-1111-111111111111",
        }
    )
    fallback = validate_metadata({"tool_type": "custom"})

    assert isinstance(composio, ComposioMetadata)
    assert isinstance(fallback, MCPMetadata)
    assert fallback.tool_type == "custom"


def test_mcp_setting_list_get_by_id_returns_match_or_none():
    setting_list = MCPSettingList(
        settings=[
            _setting(
                "11111111-1111-1111-1111-111111111111",
                is_active=True,
                servers={"server-a": _stdio_server("npx")},
            ),
            _setting(
                "22222222-2222-2222-2222-222222222222",
                is_active=False,
                servers={"server-b": _stdio_server("uvx")},
            ),
        ]
    )

    assert str(setting_list.get_by_id(UUID("11111111-1111-1111-1111-111111111111")).id) == (
        "11111111-1111-1111-1111-111111111111"
    )
    assert setting_list.get_by_id(UUID("44444444-4444-4444-4444-444444444444")) is None


def test_get_combined_active_config_merges_and_skips_codex_as_mcp():
    active_1 = _setting(
        "11111111-1111-1111-1111-111111111111",
        is_active=True,
        servers={
            "codex-as-mcp": _stdio_server("uvx"),
            "shared-server": _stdio_server("npx"),
        },
        metadata=CodexMetadata(auth_json={"OPENAI_API_KEY": "k"}, store_path=""),
    )
    inactive = _setting(
        "22222222-2222-2222-2222-222222222222",
        is_active=False,
        servers={"inactive-server": _stdio_server("python")},
    )
    active_2 = _setting(
        "33333333-3333-3333-3333-333333333333",
        is_active=True,
        servers={
            "shared-server": _stdio_server("uvx"),
            "remote-server": _remote_server("https://remote.example/mcp"),
        },
        metadata=ComposioMetadata(
            toolkit_slug="github",
            toolkit_name="GitHub",
            profile_id="22222222-2222-2222-2222-222222222222",
        ),
    )
    setting_list = MCPSettingList(settings=[active_1, inactive, active_2])

    combined = setting_list.get_combined_active_config()
    combined_dict = setting_list.get_combined_active_config_dict()

    assert "codex-as-mcp" not in combined.mcpServers
    assert combined.mcpServers["shared-server"].command == "uvx"
    assert combined.mcpServers["remote-server"].type == "remote"
    assert len(combined.metadatas) == 2
    assert set(combined_dict["mcpServers"].keys()) == {"shared-server", "remote-server"}
