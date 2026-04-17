"""Pydantic schemas (DTOs) for mcp_settings domain."""

import json
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from fastmcp.mcp_config import RemoteMCPServer, StdioMCPServer
from pydantic import BaseModel, Field

from ii_agent.core.logger import logger


class MCPMetadata(BaseModel):
    """Model for MCP Metadata"""

    tool_type: str = Field(..., description="Type of MCP tool (e.g., 'codex', 'firebase', etc.)")


class CodexMetadata(MCPMetadata):
    """Metadata specific to Codex MCP tool."""

    tool_type: str = Field(default="codex", description="Tool type is always 'codex'")
    auth_json: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Codex authentication JSON. Only populated for trusted internal consumers.",
    )
    encrypted_auth_json: Optional[str] = Field(
        default=None,
        description="Encrypted Codex authentication JSON stored server-side",
    )
    provider_connection_id: Optional[UUID] = Field(
        default=None,
        description="Stored provider connection backing this runtime",
    )
    has_auth: bool = Field(default=False, description="Whether Codex auth is configured")
    auth_mode: Optional[str] = Field(
        default=None,
        description="Authentication mode (api_key, manual_auth_json, openai_oauth)",
    )
    oauth_provider: Optional[str] = Field(
        default=None,
        description="OAuth provider for Codex auth, when applicable",
    )
    oauth_connected_at: Optional[str] = Field(
        default=None,
        description="When the OpenAI OAuth connection was established",
    )
    chatgpt_plan_type: Optional[str] = Field(
        default=None,
        description="ChatGPT plan type derived from OpenAI auth claims",
    )
    chatgpt_account_id: Optional[str] = Field(
        default=None,
        description="ChatGPT workspace/account ID derived from OpenAI auth claims",
    )
    store_path: str = Field(default="~/.codex", description="Path where Codex stores its data")
    model: Optional[str] = Field(default=None, description="Optional model to start Codex with")
    model_reasoning_effort: Optional[str] = Field(
        default=None, description="Reasoning effort of model"
    )
    search: bool = Field(default=False, description="Whether Codex search is enabled")


class ClaudeCodeMetadata(MCPMetadata):
    """Metadata specific to Claude Code MCP tool."""

    tool_type: str = Field(default="claude_code", description="Tool type is always 'claude_code'")
    auth_json: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Claude Code authentication JSON (access_token, refresh_token, expires_at)",
    )
    provider_connection_id: Optional[UUID] = Field(
        default=None,
        description="Stored provider connection backing this runtime",
    )
    has_auth: bool = Field(default=False, description="Whether Claude Code auth is configured")
    store_path: str = Field(
        default="~/.claude", description="Path where Claude Code stores its data"
    )


class ComposioMetadata(MCPMetadata):
    """Metadata specific to Composio MCP tool."""

    tool_type: str = Field(default="composio", description="Tool type is always 'composio'")
    toolkit_slug: str = Field(..., description="Composio toolkit slug (e.g., 'gmail')")
    toolkit_name: str = Field(..., description="Composio toolkit display name")
    profile_id: UUID = Field(..., description="Composio profile ID")


MCPMetadataType = Union[CodexMetadata, ClaudeCodeMetadata, ComposioMetadata, MCPMetadata]


def validate_metadata(metadata_dict: Dict[str, Any]) -> MCPMetadataType:
    """
    Validate and convert a metadata dictionary to the appropriate typed metadata model.

    Args:
        metadata_dict: Raw metadata dictionary from database

    Returns:
        Validated metadata object of the appropriate type

    Raises:
        ValueError: If tool_type is unknown or validation fails
    """
    if not metadata_dict:
        raise ValueError("Metadata cannot be empty")

    tool_type = metadata_dict.get("tool_type")

    if tool_type == "codex":
        processed_metadata = metadata_dict.copy()
        auth_json = processed_metadata.get("auth_json")
        if isinstance(auth_json, str):
            try:
                processed_metadata["auth_json"] = json.loads(auth_json)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON in auth_json field: {auth_json}")

        return CodexMetadata(**processed_metadata)
    elif tool_type == "claude_code":
        processed_metadata = metadata_dict.copy()
        auth_json = processed_metadata.get("auth_json")
        if isinstance(auth_json, str):
            try:
                processed_metadata["auth_json"] = json.loads(auth_json)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON in auth_json field: {auth_json}")

        return ClaudeCodeMetadata(**processed_metadata)
    elif tool_type == "composio":
        return ComposioMetadata(**metadata_dict)
    else:
        # Fallback to base metadata for unknown types
        return MCPMetadata(**metadata_dict)


class MCPServersConfig(BaseModel):
    """Configuration for all MCP servers."""

    mcpServers: Dict[str, StdioMCPServer | RemoteMCPServer] = Field(
        default_factory=dict, description="Map of server names to their configurations"
    )
    metadatas: List[MCPMetadataType] = Field(
        default_factory=list, description="Map of server names to their configurations"
    )


class CodexConfigConfigure(BaseModel):
    """Request model for configuring Codex MCP."""

    auth_json: Optional[Dict[str, Any]] = Field(None, description="Codex authentication JSON")
    apikey: Optional[str] = Field(None, description="Connect to codex with apikey")
    model: Optional[str] = Field(None, description="Optional model to start codex with")
    model_reasoning_effort: Optional[str] = Field(None, description="reasoning effort of model")
    search: bool = Field(False, description="toggle search for codex")


class ClaudeCodeConfigConfigure(BaseModel):
    """Request model for configuring Claude Code MCP."""

    authorization_code: str = Field(..., description="OAuth authorization code from Claude")


class ClaudeCodeOAuthStartRequest(BaseModel):
    """Request model for starting the Claude Code OAuth flow."""

    redirect_uri: str = Field(..., description="Frontend callback URI for popup completion")


class ClaudeCodeOAuthStartResponse(BaseModel):
    """Response returned when starting the Claude Code OAuth flow."""

    login_id: str
    authorization_url: str


class ClaudeCodeOAuthCompleteRequest(BaseModel):
    """Request model for completing the Claude Code OAuth flow."""

    login_id: str
    code: str
    state: str


class CodexOpenAIDeviceStartRequest(BaseModel):
    """Request model for starting the OpenAI Codex device-code flow."""

    model: Optional[str] = Field(None, description="Optional model to start Codex with")
    model_reasoning_effort: Optional[str] = Field(None, description="Reasoning effort of model")
    search: bool = Field(False, description="Toggle search for Codex")


class CodexOpenAIDeviceStartResponse(BaseModel):
    """Response returned when starting the OpenAI Codex device-code flow."""

    login_id: str
    verification_url: str
    user_code: str
    interval_seconds: int
    expires_in_seconds: int


class MCPSettingCreate(BaseModel):
    """Model for creating/updating MCP settings."""

    mcp_config: MCPServersConfig = Field(..., description="MCP configuration object")
    metadata: Optional[MCPMetadataType] = Field(None, description="Additional metadata")


class MCPSettingUpdate(BaseModel):
    """Model for updating existing MCP settings."""

    mcp_config: Optional[MCPServersConfig] = Field(None, description="MCP configuration object")
    metadata: Optional[MCPMetadataType] = Field(None, description="Additional metadata")
    is_active: Optional[bool] = Field(None, description="Whether the MCP setting is active")


class MCPDefaultSelectionUpdate(BaseModel):
    """Request model for updating the user's default MCP runtime."""

    setting_id: Optional[UUID] = Field(
        default=None,
        description="MCP setting ID to use as default, or null to clear the default",
    )


class MCPDefaultSelectionInfo(BaseModel):
    """Response model for the user's default MCP runtime selection."""

    default_mcp_setting_id: Optional[UUID] = None


class MCPSettingInfo(BaseModel):
    """Model for MCP setting information."""

    id: UUID
    mcp_config: MCPServersConfig
    metadata: Optional[MCPMetadataType] = None
    is_active: bool
    created_at: str
    updated_at: Optional[str] = None


class CodexOpenAIDevicePollRequest(BaseModel):
    """Request model for polling an OpenAI Codex device-code login."""

    login_id: str


class CodexOpenAIDevicePollResponse(BaseModel):
    """Status response for an OpenAI Codex device-code login."""

    status: Literal["pending", "completed", "error"]
    setting: Optional[MCPSettingInfo] = None
    error: Optional[str] = None


class MCPSettingList(BaseModel):
    """Model for MCP setting list response."""

    settings: List[MCPSettingInfo]

    def get_by_id(self, setting_id: UUID) -> Optional[MCPSettingInfo]:
        """Get MCP setting by ID."""
        return next(
            (setting for setting in self.settings if setting.id == setting_id),
            None,
        )

    def get_combined_active_config(self) -> MCPServersConfig:
        """Combine all active MCP settings into a single configuration.

        Each active MCP setting contributes its servers to the combined config.
        If multiple settings have servers with the same name, the last one wins.

        Returns:
            MCPServersConfig: Combined configuration with all active MCP servers
        """
        combined_servers: Dict[str, StdioMCPServer | RemoteMCPServer] = {}
        metadatas: List[MCPMetadataType] = []

        # Iterate through all active settings
        for setting in self.settings:
            if setting.is_active and setting.mcp_config and setting.mcp_config.mcpServers:
                # Add or update servers from this setting
                for server_name, server_config in setting.mcp_config.mcpServers.items():
                    # HACK:Skip codex-as-mcp since it's handled separately by register_codex()
                    if server_name == "codex-as-mcp":
                        logger.info(f"Config of codex: {server_config} skipped")
                    else:
                        combined_servers[server_name] = server_config

                if setting.metadata:
                    metadatas.append(setting.metadata)

        logger.debug(f"metadatas: {metadatas}")

        return MCPServersConfig(mcpServers=combined_servers, metadatas=metadatas)

    def get_combined_active_config_dict(self) -> Dict[str, Any]:
        """Get combined active MCP configuration as a dictionary.

        Returns:
            Dict: Combined configuration in the format {"mcpServers": {...}, "metadatas": [...]}
        """
        combined_config = self.get_combined_active_config()
        return combined_config.model_dump(exclude_none=True)
