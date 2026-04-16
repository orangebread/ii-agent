export interface GoogleAuthRequest {
    code: string
    redirect_uri: string
}

export interface AuthProvidersResponse {
    ii_oauth_available: boolean
    google_oauth_available: boolean
    dev_auth_bypass_enabled: boolean
}

export interface AuthTokenResponse {
    access_token: string
    refresh_token: string
    token_type: string
    expires_in: number
}

export type GoogleAuthResponse = AuthTokenResponse

export interface OpenAIDeviceStartRequest {
    model?: string
    model_reasoning_effort?: string
    search?: boolean
}

export interface OpenAIDeviceStartResponse {
    login_id: string
    verification_url: string
    user_code: string
    interval_seconds: number
    expires_in_seconds: number
}

export interface OpenAIDevicePollRequest {
    login_id: string
}

export interface OpenAIDevicePollResponse {
    status: 'pending' | 'completed' | 'error'
    continue_with_ii: boolean
    pending_connect_id?: string
    error?: string
}

export interface RefreshTokenResponse {
    accessToken: string
}

export interface CurrentUserResponse {
    id: string
    name: string
    email: string
    picture?: string
}
