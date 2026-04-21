import axiosInstance from '@/lib/axios'
import {
    ClaudeCodeOAuthStartResponse,
    CodexOpenAIDevicePollResponse,
    CodexOpenAIDeviceStartResponse,
    GetAvailableModelsResponse,
    GetMcpSettingsResponse,
    GetSkillsResponse,
    IMcpSettings,
    IModel,
    ISkill,
    UpdateMcpSettingsPayload
} from '@/typings/settings'

class SettingsService {
    async createModel(payload: IModel): Promise<IModel> {
        const response = await axiosInstance.post<IModel>(
            '/v1/user-settings/models',
            payload
        )
        return response.data
    }

    async updateModel(id: string, payload: Partial<IModel>): Promise<IModel> {
        const response = await axiosInstance.put<IModel>(
            `/v1/user-settings/models/${id}`,
            payload
        )
        return response.data
    }

    async deleteModel(id: string): Promise<void> {
        await axiosInstance.delete(`/v1/user-settings/models/${id}`)
    }

    async getAvailableModels(): Promise<GetAvailableModelsResponse> {
        const response = await axiosInstance.get<GetAvailableModelsResponse>(
            `/v1/user-settings/models`
        )
        return response.data
    }

    async getModelById(id: string): Promise<IModel> {
        const response = await axiosInstance.get<IModel>(
            `/v1/user-settings/models/${id}`
        )
        return response.data
    }

    async getMcpSettings(): Promise<GetMcpSettingsResponse> {
        const response =
            await axiosInstance.get<GetMcpSettingsResponse>(
                '/v1/user-settings/mcp'
            )
        return response.data
    }

    async createMcpSettings(
        payload: UpdateMcpSettingsPayload
    ): Promise<IMcpSettings> {
        const response = await axiosInstance.post<IMcpSettings>(
            '/v1/user-settings/mcp',
            payload
        )
        return response.data
    }

    async updateMcpSettings(
        id: string,
        payload: UpdateMcpSettingsPayload
    ): Promise<IMcpSettings> {
        const response = await axiosInstance.put<IMcpSettings>(
            `/v1/user-settings/mcp/${id}`,
            payload
        )
        return response.data
    }

    async deleteMcpSettings(id: string): Promise<void> {
        await axiosInstance.delete(`/v1/user-settings/mcp/${id}`)
    }

    async getCodexSettings(): Promise<IMcpSettings | null> {
        const response = await axiosInstance.get<IMcpSettings | null>(
            '/v1/user-settings/mcp/codex'
        )
        return response.data
    }

    async getClaudeCodeSettings(): Promise<IMcpSettings | null> {
        const response = await axiosInstance.get<IMcpSettings | null>(
            '/v1/user-settings/mcp/claude-code'
        )
        return response.data
    }

    async configureCodex(payload: {
        auth_json?: object
        model?: string
        apikey?: string
        model_reasoning_effort?: string
        search?: boolean
    }): Promise<IMcpSettings> {
        const response = await axiosInstance.post<IMcpSettings>(
            '/v1/user-settings/mcp/codex',
            payload
        )
        return response.data
    }

    async startCodexOpenAIDeviceOAuth(payload: {
        model?: string
        model_reasoning_effort?: string
        search?: boolean
    }): Promise<CodexOpenAIDeviceStartResponse> {
        const response = await axiosInstance.post<CodexOpenAIDeviceStartResponse>(
            '/v1/user-settings/mcp/codex/openai/device/start',
            payload
        )
        return response.data
    }

    async pollCodexOpenAIDeviceOAuth(payload: {
        login_id: string
    }): Promise<CodexOpenAIDevicePollResponse> {
        const response = await axiosInstance.post<CodexOpenAIDevicePollResponse>(
            '/v1/user-settings/mcp/codex/openai/device/poll',
            payload
        )
        return response.data
    }

    async configureClaudeCode(payload: {
        authorization_code?: string
    }): Promise<IMcpSettings> {
        const response = await axiosInstance.post<IMcpSettings>(
            '/v1/user-settings/mcp/claude-code',
            payload
        )
        return response.data
    }

    async deleteClaudeCodeSettings(): Promise<void> {
        await axiosInstance.delete('/v1/user-settings/mcp/claude-code')
    }

    async startClaudeCodeOAuth(payload: {
        redirect_uri: string
    }): Promise<ClaudeCodeOAuthStartResponse> {
        const response = await axiosInstance.post<ClaudeCodeOAuthStartResponse>(
            '/v1/user-settings/mcp/claude-code/oauth/start',
            payload
        )
        return response.data
    }

    async completeClaudeCodeOAuth(payload: {
        login_id: string
        code: string
        state: string
    }): Promise<IMcpSettings> {
        const response = await axiosInstance.post<IMcpSettings>(
            '/v1/user-settings/mcp/claude-code/oauth/complete',
            payload
        )
        return response.data
    }

    // Skills API methods
    async getSkills(includeBuiltin: boolean = true): Promise<GetSkillsResponse> {
        const response = await axiosInstance.get<GetSkillsResponse>(
            `/v1/user-settings/skills?include_builtin=${includeBuiltin}`
        )
        return response.data
    }

    async getSkillById(id: string): Promise<ISkill> {
        const response = await axiosInstance.get<ISkill>(
            `/v1/user-settings/skills/${id}`
        )
        return response.data
    }

    async addSkillFromGitHub(githubUrl: string): Promise<ISkill> {
        const response = await axiosInstance.post<ISkill>(
            '/v1/user-settings/skills/github',
            { github_url: githubUrl }
        )
        return response.data
    }

    async toggleSkill(id: string, isEnabled: boolean): Promise<ISkill> {
        const response = await axiosInstance.patch<ISkill>(
            `/v1/user-settings/skills/${id}/toggle`,
            { is_enabled: isEnabled }
        )
        return response.data
    }

    async deleteSkill(id: string): Promise<void> {
        await axiosInstance.delete(`/v1/user-settings/skills/${id}`)
    }
}

export const settingsService = new SettingsService()
