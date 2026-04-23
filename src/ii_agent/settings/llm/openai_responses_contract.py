"""Shared request-shaping rules for OpenAI Responses-compatible backends."""

from __future__ import annotations

from typing import Any, Sequence


_CODEX_BACKEND_PATH = "/backend-api/codex"
_REASONING_ENCRYPTED_CONTENT = "reasoning.encrypted_content"
_CODEX_RESPONSES_ALLOWED_PARAMS = frozenset(
    {
        "include",
        "input",
        "instructions",
        "model",
        "previous_response_id",
        "reasoning",
        "store",
        "stream",
        "text",
        "tool_choice",
        "tools",
    }
)


def is_reasoning_model(model_name: str) -> bool:
    """Return True when the model uses Responses reasoning session semantics."""
    return (
        model_name.startswith("o3")
        or model_name.startswith("o4-mini")
        or model_name.startswith("gpt-5")
    )


def requires_stateless_responses_backend(base_url: str | None) -> bool:
    """Return True when the target backend rejects stored Responses state."""
    return bool(base_url) and _CODEX_BACKEND_PATH in str(base_url)


def merge_responses_instructions(*parts: str | None) -> str | None:
    """Join instruction fragments into one Responses API instructions string."""
    normalized_parts = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if not normalized_parts:
        return None
    return "\n\n".join(normalized_parts)


def apply_responses_session_contract(
    *,
    model_name: str,
    base_url: str | None,
    store: bool | None = None,
    include: Sequence[str] | None = None,
    previous_response_id: str | None = None,
) -> dict[str, Any]:
    """Apply backend/model-specific Responses session requirements."""
    stateless_backend = requires_stateless_responses_backend(base_url)
    include_fields = list(include or [])
    request_params: dict[str, Any] = {}

    if is_reasoning_model(model_name):
        effective_store = False if stateless_backend or store is False else True
        request_params["store"] = effective_store

        if not effective_store:
            if _REASONING_ENCRYPTED_CONTENT not in include_fields:
                include_fields.append(_REASONING_ENCRYPTED_CONTENT)
        elif previous_response_id:
            request_params["previous_response_id"] = previous_response_id
    else:
        if stateless_backend:
            request_params["store"] = False
        elif store is not None:
            request_params["store"] = store

        if previous_response_id and not stateless_backend:
            request_params["previous_response_id"] = previous_response_id

    if include_fields:
        request_params["include"] = include_fields

    return request_params


def apply_responses_request_contract(
    *,
    base_url: str | None,
    request_params: dict[str, Any],
) -> dict[str, Any]:
    """Apply backend-specific request param compatibility rules."""
    if requires_stateless_responses_backend(base_url):
        return {
            key: value
            for key, value in request_params.items()
            if key in _CODEX_RESPONSES_ALLOWED_PARAMS
        }

    return request_params


def extract_responses_error_message(exc: Exception) -> str:
    """Return the most specific provider error message available."""
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc) or "Unknown model error"

    try:
        payload = response.json()
    except Exception:
        return str(exc) or "Unknown model error"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail")
            if message:
                return str(message)

        detail = payload.get("detail")
        if detail:
            return str(detail)

        message = payload.get("message")
        if message:
            return str(message)

    return str(exc) or "Unknown model error"
