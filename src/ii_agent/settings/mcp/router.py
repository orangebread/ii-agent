"""API routes for mcp_settings domain."""

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from ii_agent.auth.dependencies import CurrentUser, DBSession
from ii_agent.settings.mcp.exceptions import MCPSettingNotFoundError
from ii_agent.settings.mcp.dependencies import MCPSettingServiceDep
from ii_agent.settings.mcp.schemas import (
    CodexConfigConfigure,
    MCPDefaultSelectionInfo,
    MCPDefaultSelectionUpdate,
    CodexOpenAIDevicePollRequest,
    CodexOpenAIDevicePollResponse,
    CodexOpenAIDeviceStartRequest,
    CodexOpenAIDeviceStartResponse,
    ClaudeCodeConfigConfigure,
    ClaudeCodeOAuthCompleteRequest,
    ClaudeCodeOAuthStartRequest,
    ClaudeCodeOAuthStartResponse,
    MCPSettingCreate,
    MCPSettingUpdate,
    MCPSettingInfo,
    MCPSettingList,
)


router = APIRouter(prefix="/mcp", tags=["User MCP Settings Management"])


@router.get("/default", response_model=MCPDefaultSelectionInfo)
async def get_default_mcp_setting(
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Get the user's default MCP runtime selection."""
    return await service.get_default_selection_info(db, user_id=current_user.id)


@router.patch("/default", response_model=MCPDefaultSelectionInfo)
async def update_default_mcp_setting(
    payload: MCPDefaultSelectionUpdate,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Update the user's default MCP runtime selection."""
    return await service.set_default_runtime_setting(
        db,
        user_id=current_user.id,
        setting_id=payload.setting_id,
    )


@router.get("/codex", response_model=Optional[MCPSettingInfo])
async def get_codex_settings(
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Get current Codex MCP settings for the user."""
    return await service.get_codex_setting(db, user_id=str(current_user.id))


@router.post("/codex", response_model=MCPSettingInfo)
async def configure_codex_mcp(
    request: CodexConfigConfigure,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Configure Codex MCP with authentication."""
    return await service.configure_codex(
        db,
        user_id=str(current_user.id),
        auth_json=request.auth_json,
        apikey=request.apikey,
        model=request.model,
        reasoning_effort=request.model_reasoning_effort,
        search=request.search,
    )


@router.post("/codex/openai/device/start", response_model=CodexOpenAIDeviceStartResponse)
async def start_codex_openai_device_oauth(
    request: CodexOpenAIDeviceStartRequest,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
):
    """Start the OpenAI Codex device-code OAuth flow."""
    return await service.start_codex_openai_device_oauth(
        user_id=str(current_user.id),
        model=request.model,
        reasoning_effort=request.model_reasoning_effort,
        search=request.search,
    )


@router.post("/codex/openai/device/poll", response_model=CodexOpenAIDevicePollResponse)
async def poll_codex_openai_device_oauth(
    request: CodexOpenAIDevicePollRequest,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Poll the OpenAI Codex device-code OAuth flow."""
    return await service.poll_codex_openai_device_oauth(
        db,
        user_id=str(current_user.id),
        login_id=request.login_id,
    )


@router.get("/claude-code", response_model=Optional[MCPSettingInfo])
async def get_claude_code_settings(
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Get current Claude Code MCP settings for the user."""
    return await service.get_claude_code_setting(db, user_id=str(current_user.id))


@router.post("/claude-code", response_model=MCPSettingInfo)
async def configure_claude_code_mcp(
    request: ClaudeCodeConfigConfigure,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Configure Claude Code MCP with OAuth authentication."""
    return await service.configure_claude_code(
        db,
        user_id=str(current_user.id),
        authorization_code=request.authorization_code,
    )


@router.delete("/claude-code")
async def delete_claude_code_mcp(
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Disconnect Claude Code and remove the stored OAuth connection."""
    deleted = await service.delete_claude_code_setting(
        db,
        user_id=str(current_user.id),
    )

    if not deleted:
        raise MCPSettingNotFoundError("Claude Code settings not found")

    return {"message": "Claude Code settings deleted successfully"}


@router.post("/claude-code/oauth/start", response_model=ClaudeCodeOAuthStartResponse)
async def start_claude_code_oauth(
    request: ClaudeCodeOAuthStartRequest,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
):
    """Start the Claude Code OAuth flow."""
    return await service.start_claude_code_oauth(
        user_id=str(current_user.id),
        redirect_uri=request.redirect_uri,
    )


@router.post("/claude-code/oauth/complete", response_model=MCPSettingInfo)
async def complete_claude_code_oauth(
    request: ClaudeCodeOAuthCompleteRequest,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Complete the Claude Code OAuth flow."""
    return await service.complete_claude_code_oauth(
        db,
        user_id=str(current_user.id),
        login_id=request.login_id,
        code=request.code,
        state=request.state,
    )


@router.get("/claude-code/oauth/callback", include_in_schema=False)
async def claude_code_oauth_callback(
    service: MCPSettingServiceDep,
    code: Optional[str] = None,
    state: str = "",
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """Bridge Anthropic's OAuth callback back to the frontend popup callback."""
    redirect_url = service.resolve_claude_code_oauth_callback_redirect(
        state=state,
        code=code,
        error=error,
        error_description=error_description,
    )
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("", response_model=MCPSettingInfo)
async def create_mcp_setting(
    setting: MCPSettingCreate,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Create new MCP settings for the current user."""
    return await service.create_mcp_settings(
        db,
        mcp_setting_in=setting,
        user_id=str(current_user.id),
    )


@router.get("", response_model=MCPSettingList)
async def list_user_mcp_settings(
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
    only_active: bool = False,
):
    """List all MCP settings for the current user."""
    return await service.list_mcp_settings(
        db,
        user_id=str(current_user.id),
        only_active=only_active,
        no_metadata=True,
    )


@router.get("/{setting_id}", response_model=MCPSettingInfo)
async def get_mcp_setting(
    setting_id: str,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Get specific MCP settings by ID."""
    return await service.get_mcp_settings(
        db,
        setting_id=setting_id,
        user_id=str(current_user.id),
    )


@router.put("/{setting_id}", response_model=MCPSettingInfo)
async def update_mcp_setting(
    setting_id: str,
    setting_update: MCPSettingUpdate,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Update existing MCP settings."""
    return await service.update_mcp_settings(
        db,
        setting_id=setting_id,
        setting_update=setting_update,
        user_id=str(current_user.id),
    )


@router.delete("/{setting_id}")
async def delete_mcp_setting(
    setting_id: str,
    current_user: CurrentUser,
    service: MCPSettingServiceDep,
    db: DBSession,
):
    """Delete MCP settings by ID."""
    deleted = await service.delete_mcp_settings(
        db,
        setting_id=setting_id,
        user_id=str(current_user.id),
    )

    if not deleted:
        raise MCPSettingNotFoundError("MCP settings not found")

    return {"message": "MCP settings deleted successfully"}
