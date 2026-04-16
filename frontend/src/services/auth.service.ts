import axiosInstance from '@/lib/axios'
import { User } from '@/state/slice/user'
import {
    AuthProvidersResponse,
    GoogleAuthResponse,
    GoogleAuthRequest,
    OpenAIDevicePollRequest,
    OpenAIDevicePollResponse,
    OpenAIDeviceStartRequest,
    OpenAIDeviceStartResponse,
    RefreshTokenResponse
} from '@/typings/auth'

class AuthService {
    async getAuthProviders(): Promise<AuthProvidersResponse> {
        const response = await axiosInstance.get<AuthProvidersResponse>(
            '/auth/providers'
        )
        return response.data
    }

    async googleAuth(params: GoogleAuthRequest): Promise<GoogleAuthResponse> {
        const response = await axiosInstance.get<GoogleAuthResponse>(
            '/auth/oauth/google/callback',
            {
                params
            }
        )
        return response.data
    }

    async startOpenAIDeviceLogin(
        payload: OpenAIDeviceStartRequest
    ): Promise<OpenAIDeviceStartResponse> {
        const response = await axiosInstance.post<OpenAIDeviceStartResponse>(
            '/auth/oauth/openai/device/start',
            payload
        )
        return response.data
    }

    async pollOpenAIDeviceLogin(
        payload: OpenAIDevicePollRequest
    ): Promise<OpenAIDevicePollResponse> {
        const response = await axiosInstance.post<OpenAIDevicePollResponse>(
            '/auth/oauth/openai/device/poll',
            payload
        )
        return response.data
    }

    async logout(): Promise<void> {
        await axiosInstance.post('/api/auth/logout')
    }

    async getCurrentUser(): Promise<User> {
        const response = await axiosInstance.get<User>('/auth/me')
        return response.data
    }

    async refreshToken(): Promise<RefreshTokenResponse> {
        const response =
            await axiosInstance.post<RefreshTokenResponse>('/auth/refresh')
        return response.data
    }
}

export const authService = new AuthService()
