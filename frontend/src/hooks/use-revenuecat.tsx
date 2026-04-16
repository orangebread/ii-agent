import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import { connectorService } from '@/services/connector.service'
import {
    connectorApi,
    useAppDispatch,
    useGetRevenueCatStatusQuery
} from '@/state'
import { ACCESS_TOKEN } from '@/constants/auth'

interface UseRevenueCatOptions {
    onConnectionSuccess?: () => void
}

export const useRevenueCat = (options?: UseRevenueCatOptions) => {
    const dispatch = useAppDispatch()
    const hasAccessToken = Boolean(localStorage.getItem(ACCESS_TOKEN))
    const { data: statusData } = useGetRevenueCatStatusQuery(undefined, {
        skip: !hasAccessToken
    })
    const isConnected = statusData?.is_connected ?? false
    const [isAuthLoading, setIsAuthLoading] = useState(false)

    const handleRevenueCatAuth = useCallback(async () => {
        setIsAuthLoading(true)
        try {
            const { auth_url } = await connectorService.getRevenueCatAuthUrl()
            const { code, state } = await connectorService.openAuthPopup(
                auth_url,
                'Connect with RevenueCat'
            )
            const response = await connectorService.handleRevenueCatCallback(
                code,
                state
            )

            if (!response.success) {
                throw new Error(
                    response.message || 'Failed to connect RevenueCat'
                )
            }

            dispatch(connectorApi.util.invalidateTags(['RevenueCatStatus']))
            toast.success('RevenueCat connected successfully')
            options?.onConnectionSuccess?.()
        } catch (error) {
            console.error('RevenueCat auth error:', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : 'Failed to connect RevenueCat'
            )
        } finally {
            setIsAuthLoading(false)
        }
    }, [dispatch, options])

    const handleRevenueCatClick = useCallback(async () => {
        if (!isConnected) {
            await handleRevenueCatAuth()
        }
    }, [handleRevenueCatAuth, isConnected])

    return {
        isConnected,
        isAuthLoading,
        handleRevenueCatClick
    }
}
