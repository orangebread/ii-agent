import json
import re
from typing import Any, Dict, Iterable, Optional

from ii_agent.core.exceptions import ValidationError
from ii_agent.core.secrets.encryption import encryption_manager

_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_valid_env_var_name(name: str) -> bool:
    """Return True when a string is a valid environment variable name."""
    return bool(_ENV_VAR_NAME_PATTERN.fullmatch(name))


def validate_env_var_names(names: Iterable[Any]) -> None:
    """Raise when any provided secret key is not a valid environment variable name."""
    invalid_names = [
        name if isinstance(name, str) else repr(name)
        for name in names
        if not isinstance(name, str) or not is_valid_env_var_name(name)
    ]
    if invalid_names:
        joined = ", ".join(sorted(invalid_names))
        raise ValidationError(f"Invalid environment variable name(s): {joined}")


def sanitize_secret_payload(payload: Any) -> tuple[Dict[str, Any], list[str]]:
    """Filter a persisted secret payload down to valid environment keys."""
    if not isinstance(payload, dict):
        return {}, []

    sanitized: Dict[str, Any] = {}
    invalid_names: list[str] = []
    for key, value in payload.items():
        if isinstance(key, str) and is_valid_env_var_name(key):
            sanitized[key] = value
        else:
            invalid_names.append(key if isinstance(key, str) else repr(key))

    return sanitized, invalid_names


def _encrypt_secrets_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    serialized = json.dumps(payload)
    encrypted = encryption_manager.encrypt(serialized)
    return {"encrypted_data": encrypted}


def _decrypt_secrets_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not payload:
        return None

    encrypted_value = payload.get("encrypted_data") if isinstance(payload, dict) else None
    if not encrypted_value:
        return payload

    decrypted = encryption_manager.decrypt(encrypted_value)
    if not decrypted:
        return None
    try:
        return json.loads(decrypted)
    except json.JSONDecodeError:
        return None
