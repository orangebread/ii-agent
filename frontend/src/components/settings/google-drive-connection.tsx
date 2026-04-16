import { useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { ACCESS_TOKEN } from '@/constants/auth'
import { cn } from '@/lib/utils'
import { connectorService } from '@/services/connector.service'
import {
    useGetGoogleDriveStatusQuery,
    useDisconnectGoogleDriveMutation,
    connectorApi,
    useAppDispatch
} from '@/state'

type GoogleDriveAction = 'connect' | 'disconnect' | null

export const GoogleDriveConnection = () => {
    const { t } = useTranslation()
    const dispatch = useAppDispatch()
    const hasAccessToken = Boolean(localStorage.getItem(ACCESS_TOKEN))
    const { data: statusData, isLoading: isGoogleDriveLoading } =
        useGetGoogleDriveStatusQuery(undefined, {
            skip: !hasAccessToken
        })
    const isGoogleDriveConnected = statusData?.is_connected ?? false
    const [disconnectGoogleDrive] = useDisconnectGoogleDriveMutation()

    const [isGoogleDriveProcessing, setIsGoogleDriveProcessing] =
        useState(false)
    const [googleDriveAction, setGoogleDriveAction] =
        useState<GoogleDriveAction>(null)

    const handleGoogleDriveConnect = async () => {
        if (isGoogleDriveProcessing) return

        setIsGoogleDriveProcessing(true)
        setGoogleDriveAction('connect')
        try {
            const { auth_url } = await connectorService.getGoogleDriveAuthUrl()
            const { code, state } =
                await connectorService.openAuthPopup(auth_url)
            const result = await connectorService.handleGoogleDriveCallback(
                code,
                state
            )

            if (!result.success) {
                throw new Error(
                    result.message ||
                        t('connectors.googleDrive.errors.connectFailed')
                )
            }

            // Invalidate the cache to refetch the status
            dispatch(
                connectorApi.util.invalidateTags(['GoogleDriveStatus'])
            )
            toast.success(t('connectors.googleDrive.toasts.connected'))
        } catch (error) {
            console.error('Failed to connect Google Drive', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : t('connectors.googleDrive.errors.connectFailed')
            )
        } finally {
            setIsGoogleDriveProcessing(false)
            setGoogleDriveAction(null)
        }
    }

    const handleGoogleDriveDisconnect = async () => {
        if (isGoogleDriveProcessing) return

        setIsGoogleDriveProcessing(true)
        setGoogleDriveAction('disconnect')
        try {
            // Use RTK Query mutation - it will automatically invalidate the cache
            const result = await disconnectGoogleDrive().unwrap()

            if (!result.success) {
                throw new Error(
                    result.message ||
                        t('connectors.googleDrive.errors.disconnectFailed')
                )
            }

            toast.success(t('connectors.googleDrive.toasts.disconnected'))
        } catch (error) {
            console.error('Failed to disconnect Google Drive', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : t('connectors.googleDrive.errors.disconnectFailed')
            )
        } finally {
            setIsGoogleDriveProcessing(false)
            setGoogleDriveAction(null)
        }
    }

    const googleDriveButtonLabel = (() => {
        if (isGoogleDriveLoading) return t('connectors.status.checking')
        if (isGoogleDriveProcessing) {
            return googleDriveAction === 'disconnect'
                ? t('connectors.status.disconnecting')
                : t('connectors.status.connecting')
        }
        return isGoogleDriveConnected
            ? t('connectors.googleDrive.disconnect')
            : t('connectors.googleDrive.connect')
    })()

    return (
        <div className="flex items-center justify-between">
            <p className="text-sm">{t('connectors.googleDrive.title')}</p>
            <Button
                className={cn(
                    'underline p-0 h-auto text-black/[0.56] dark:text-white/[0.56]',
                    isGoogleDriveConnected &&
                        'text-red-600 dark:text-red-400'
                )}
                disabled={
                    isGoogleDriveLoading || isGoogleDriveProcessing
                }
                onClick={
                    isGoogleDriveConnected
                        ? handleGoogleDriveDisconnect
                        : handleGoogleDriveConnect
                }
            >
                {googleDriveButtonLabel}
            </Button>
        </div>
    )
}
