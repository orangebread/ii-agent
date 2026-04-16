import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { ACCESS_TOKEN } from '@/constants/auth'
import { cn } from '@/lib/utils'
import { connectorService } from '@/services/connector.service'
import {
    useGetGitHubStatusQuery,
    useDisconnectGitHubMutation,
    connectorApi,
    useAppDispatch
} from '@/state'

type GitHubAction = 'connect' | 'disconnect' | null

export const GitHubConnection = () => {
    const { t } = useTranslation()
    const dispatch = useAppDispatch()
    const hasAccessToken = Boolean(localStorage.getItem(ACCESS_TOKEN))
    const { data: statusData, isLoading: isGitHubLoading } =
        useGetGitHubStatusQuery(undefined, {
            skip: !hasAccessToken
        })
    const isGitHubConnected = statusData?.is_connected ?? false
    const [disconnectGitHub] = useDisconnectGitHubMutation()

    const [isGitHubProcessing, setIsGitHubProcessing] = useState(false)
    const [gitHubAction, setGitHubAction] = useState<GitHubAction>(null)
    const [installationUrl, setInstallationUrl] = useState<string | null>(null)

    // Fetch app config separately (not frequently accessed, so no need for RTK Query)
    useEffect(() => {
        if (!hasAccessToken) {
            return
        }

        connectorService.getGitHubAppConfig().then((appConfig) => {
            setInstallationUrl(appConfig.installation_url)
        }).catch((error) => {
            console.error('Failed to load GitHub app config', error)
        })
    }, [hasAccessToken])

    const handleGitHubConnect = async () => {
        if (isGitHubProcessing) return

        setIsGitHubProcessing(true)
        setGitHubAction('connect')
        try {
            const { auth_url } = await connectorService.getGitHubAuthUrl()
            const { code, state } = await connectorService.openAuthPopup(
                auth_url,
                t('connectors.github.authPopupTitle')
            )
            const result = await connectorService.handleGitHubCallback(
                code,
                state
            )

            if (!result.success) {
                throw new Error(
                    result.message ||
                        t('connectors.github.errors.connectFailed')
                )
            }

            // Invalidate the cache to refetch the status
            dispatch(connectorApi.util.invalidateTags(['GitHubStatus']))
            toast.success(t('connectors.github.toasts.connected'))
        } catch (error) {
            console.error('Failed to connect GitHub', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : t('connectors.github.errors.connectFailed')
            )
        } finally {
            setIsGitHubProcessing(false)
            setGitHubAction(null)
        }
    }

    const handleGitHubDisconnect = async () => {
        if (isGitHubProcessing) return

        setIsGitHubProcessing(true)
        setGitHubAction('disconnect')
        try {
            // Use RTK Query mutation - it will automatically invalidate the cache
            const result = await disconnectGitHub().unwrap()

            if (!result.success) {
                throw new Error(
                    result.message ||
                        t('connectors.github.errors.disconnectFailed')
                )
            }

            toast.success(t('connectors.github.toasts.disconnected'))
        } catch (error) {
            console.error('Failed to disconnect GitHub', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : t('connectors.github.errors.disconnectFailed')
            )
        } finally {
            setIsGitHubProcessing(false)
            setGitHubAction(null)
        }
    }

    const gitHubButtonLabel = (() => {
        if (isGitHubLoading) return t('connectors.status.checking')
        if (isGitHubProcessing) {
            return gitHubAction === 'disconnect'
                ? t('connectors.status.disconnecting')
                : t('connectors.status.connecting')
        }
        return isGitHubConnected
            ? t('connectors.github.disconnect')
            : t('connectors.github.connect')
    })()

    return (
        <div className="flex items-center justify-between">
            <p className="text-sm">{t('connectors.github.title')}</p>
            <div className="flex items-center gap-3">
                {isGitHubConnected && installationUrl && (
                    <Button
                        className="underline p-0 h-auto text-black/[0.56] dark:text-white/[0.56]"
                        disabled={isGitHubLoading || isGitHubProcessing}
                        onClick={() => {
                            window.open(
                                installationUrl,
                                '_blank',
                                'noopener,noreferrer'
                            )
                        }}
                    >
                        {t('connectors.github.configureRepos')}
                    </Button>
                )}
                <Button
                    className={cn(
                        'underline p-0 h-auto text-black/[0.56] dark:text-white/[0.56]',
                        isGitHubConnected && 'text-red-600 dark:text-red-400'
                    )}
                    disabled={isGitHubLoading || isGitHubProcessing}
                    onClick={
                        isGitHubConnected
                            ? handleGitHubDisconnect
                            : handleGitHubConnect
                    }
                >
                    {gitHubButtonLabel}
                </Button>
            </div>
        </div>
    )
}
