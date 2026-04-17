from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ii_agent.integrations.connectors.composio.client import ComposioClient


@pytest.fixture(autouse=True)
def reset_composio_client():
    ComposioClient.reset()
    yield
    ComposioClient.reset()


def test_get_client_logs_sanitized_diagnostics_for_dotenv_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    monkeypatch.delenv("COMPOSIO_BASE_URL", raising=False)
    (tmp_path / ".env").write_text("COMPOSIO_API_KEY=ck_test_abcdef123456\n", encoding="utf-8")

    fake_logger = MagicMock()
    fake_logger.bind.return_value = fake_logger

    with (
        patch(
            "ii_agent.integrations.connectors.composio.client.get_settings",
            return_value=SimpleNamespace(
                composio_api_key="ck_test_abcdef123456",
                environment="local",
            ),
        ),
        patch("ii_agent.integrations.connectors.composio.client.Composio", return_value=object()),
        patch("ii_agent.integrations.connectors.composio.client.logger", fake_logger),
    ):
        ComposioClient.get_client()

    fake_logger.bind.assert_called_once()
    bind_kwargs = fake_logger.bind.call_args.kwargs
    assert bind_kwargs["composio_api_key_source"] == "dotenv"
    assert bind_kwargs["composio_api_key_masked"] == "ck_test_*****3456"
    assert bind_kwargs["composio_base_url"] == "https://backend.composio.dev"
    assert bind_kwargs["composio_base_url_source"] == "default"
    assert bind_kwargs["app_environment"] == "local"
    assert "abcdef123456" not in str(fake_logger.bind.call_args)


def test_get_client_prefers_explicit_override_source(monkeypatch):
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)

    context = None
    with patch(
        "ii_agent.integrations.connectors.composio.client.get_settings",
        return_value=SimpleNamespace(composio_api_key="ck_settings_1234", environment="local"),
    ):
        context = ComposioClient._resolve_client_context("ck_override_9876")

    assert context["api_key_source"] == "override"
    assert context["api_key_masked"] == "ck_overr*****9876"


def test_get_client_warns_when_cached_singleton_uses_different_key():
    with patch("pathlib.Path.exists", return_value=False):
        fake_logger = MagicMock()
        fake_logger.bind.return_value = fake_logger

        with (
            patch(
                "ii_agent.integrations.connectors.composio.client.get_settings",
                return_value=SimpleNamespace(
                    composio_api_key="ck_first_123456", environment="local"
                ),
            ),
            patch(
                "ii_agent.integrations.connectors.composio.client.Composio", return_value=object()
            ),
            patch("ii_agent.integrations.connectors.composio.client.logger", fake_logger),
        ):
            ComposioClient.get_client()
            ComposioClient.get_client("ck_second_654321")

        assert fake_logger.warning.call_count == 1
        warning_bind = fake_logger.bind.call_args.kwargs
        assert warning_bind["requested_composio_api_key_source"] == "override"
        assert warning_bind["cached_composio_api_key_source"] == "settings"
