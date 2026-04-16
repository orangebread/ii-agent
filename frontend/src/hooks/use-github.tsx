import { useState, useCallback } from 'react'
import { connectorService, type GitHubRepository } from '@/services/connector.service'
import { toast } from 'sonner'
import { AxiosError } from 'axios'
import { useGetGitHubStatusQuery, connectorApi, useAppDispatch } from '@/state'
import { ACCESS_TOKEN } from '@/constants/auth'

interface ErrorResponse {
    detail?: string
}

const isUnauthorizedError = (error: unknown): boolean => {
    return error instanceof AxiosError && error.response?.status === 401
}

const getErrorDetail = (error: unknown): string => {
    if (error instanceof AxiosError) {
        const detail = (error.response?.data as ErrorResponse)?.detail
        return detail || 'GitHub authorization needs to be updated. Please reconnect.'
    }
    return 'GitHub authorization needs to be updated. Please reconnect.'
}

const handleAuthError = (
    error: unknown,
    toastId?: string | number
) => {
    if (isUnauthorizedError(error)) {
        const detail = getErrorDetail(error)
        toast.error(detail, toastId ? { id: toastId, duration: 5000 } : { duration: 5000 })
        return true
    }
    return false
}

interface UseGitHubOptions {
    onConnectionSuccess?: () => void
}

export const useGitHub = (options?: UseGitHubOptions) => {
    const dispatch = useAppDispatch()
    const hasAccessToken = Boolean(localStorage.getItem(ACCESS_TOKEN))
    const { data: statusData } = useGetGitHubStatusQuery(undefined, {
        skip: !hasAccessToken
    })
    const isConnected = statusData?.is_connected ?? false

    const [isAuthLoading, setIsAuthLoading] = useState(false)

    const handleGitHubAuth = useCallback(async () => {
        setIsAuthLoading(true)
        try {
            const { auth_url } = await connectorService.getGitHubAuthUrl()

            const { code, state } = await connectorService.openAuthPopup(
                auth_url,
                'Connect with GitHub'
            )

            const response = await connectorService.handleGitHubCallback(
                code,
                state
            )

            if (response.success) {
                // Invalidate the cache to refetch the status
                dispatch(connectorApi.util.invalidateTags(['GitHubStatus']))
                toast.success('GitHub connected successfully')
                // Call the success callback if provided
                options?.onConnectionSuccess?.()
            } else {
                throw new Error(response.message || 'Failed to connect GitHub')
            }
        } catch (error: unknown) {
            console.error('GitHub auth error:', error)
            if (!handleAuthError(error)) {
                toast.error(
                    error instanceof Error
                        ? error.message
                        : 'Failed to connect GitHub'
                )
            }
        } finally {
            setIsAuthLoading(false)
        }
    }, [options])

    const handleGitHubClick = useCallback(async () => {
        if (!isConnected) {
            await handleGitHubAuth()
        }
    }, [isConnected, handleGitHubAuth])

    const handleRepositorySelect = useCallback((repository: GitHubRepository) => {
        console.log('Repository selected:', repository)
        toast.success(`Selected: ${repository.full_name}`)
        // TODO: Implement repository selection logic
        // This could trigger navigation, add to context, etc.
    }, [])

    return {
        isConnected,
        isAuthLoading,
        handleGitHubClick,
        handleRepositorySelect,
        checkConnectionStatus: () => {} // Keep for backwards compatibility, but no-op since RTK Query handles it
    }
}
