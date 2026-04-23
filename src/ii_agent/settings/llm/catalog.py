"""Repo-owned model catalog used for managed provider-backed model rows."""

from __future__ import annotations

from dataclasses import dataclass

from ii_agent.settings.llm.types import Provider


@dataclass(frozen=True)
class ManagedModelCatalogEntry:
    """A model that II-Agent can surface when a provider connection exists."""

    model_id: str
    provider: Provider
    display_name: str
    runtime_product: str

    @property
    def setting_model_id(self) -> str:
        """Stable internal key for provider-managed rows."""
        return f"{self.runtime_product}:{self.model_id}"


ANTHROPIC_OAUTH_MODELS: tuple[ManagedModelCatalogEntry, ...] = (
    ManagedModelCatalogEntry(
        model_id="claude-sonnet-4-5-20250929",
        provider=Provider.ANTHROPIC,
        display_name="Claude Sonnet 4.5",
        runtime_product="claude_code",
    ),
    ManagedModelCatalogEntry(
        model_id="claude-sonnet-4-20250514",
        provider=Provider.ANTHROPIC,
        display_name="Claude Sonnet 4",
        runtime_product="claude_code",
    ),
    ManagedModelCatalogEntry(
        model_id="claude-opus-4-20250514",
        provider=Provider.ANTHROPIC,
        display_name="Claude Opus 4",
        runtime_product="claude_code",
    ),
    ManagedModelCatalogEntry(
        model_id="claude-3-7-sonnet-20250219",
        provider=Provider.ANTHROPIC,
        display_name="Claude 3.7 Sonnet",
        runtime_product="claude_code",
    ),
)

CODEX_OAUTH_MODELS: tuple[ManagedModelCatalogEntry, ...] = (
    ManagedModelCatalogEntry(
        model_id="gpt-5.4",
        provider=Provider.OPENAI,
        display_name="GPT-5.4",
        runtime_product="codex",
    ),
    ManagedModelCatalogEntry(
        model_id="gpt-5.4-mini",
        provider=Provider.OPENAI,
        display_name="GPT-5.4 Mini",
        runtime_product="codex",
    ),
    ManagedModelCatalogEntry(
        model_id="gpt-5.3-codex",
        provider=Provider.OPENAI,
        display_name="GPT-5.3 Codex",
        runtime_product="codex",
    ),
    ManagedModelCatalogEntry(
        model_id="gpt-5.2",
        provider=Provider.OPENAI,
        display_name="GPT-5.2",
        runtime_product="codex",
    ),
)

MANAGED_PROVIDER_MODEL_CATALOG: dict[tuple[str, str], tuple[ManagedModelCatalogEntry, ...]] = {
    (Provider.ANTHROPIC.value, "claude_code"): ANTHROPIC_OAUTH_MODELS,
    (Provider.OPENAI.value, "codex"): CODEX_OAUTH_MODELS,
}

MANAGED_MODEL_CATALOG_BY_PROVIDER_AND_ID: dict[tuple[str, str], ManagedModelCatalogEntry] = {
    (entry.provider.value, entry.model_id): entry
    for catalog in MANAGED_PROVIDER_MODEL_CATALOG.values()
    for entry in catalog
}

MANAGED_MODEL_CATALOG_BY_SETTING_ID: dict[str, ManagedModelCatalogEntry] = {
    entry.setting_model_id: entry
    for catalog in MANAGED_PROVIDER_MODEL_CATALOG.values()
    for entry in catalog
}
