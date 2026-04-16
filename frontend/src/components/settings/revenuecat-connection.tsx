import { useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ACCESS_TOKEN } from '@/constants/auth'
import { cn } from '@/lib/utils'
import { connectorService } from '@/services/connector.service'
import {
    connectorApi,
    useAppDispatch,
    useDisconnectRevenueCatMutation,
    useGetRevenueCatStatusQuery
} from '@/state'

type RevenueCatAction = 'connect' | 'disconnect' | null
type RevenueCatConnectionVariant = 'settings' | 'project'

interface RevenueCatConnectionProps {
    variant?: RevenueCatConnectionVariant
}

export const RevenueCatConnection = ({
    variant = 'settings'
}: RevenueCatConnectionProps) => {
    const { t } = useTranslation()
    const dispatch = useAppDispatch()
    const hasAccessToken = Boolean(localStorage.getItem(ACCESS_TOKEN))
    const { data: statusData, isLoading: isRevenueCatLoading } =
        useGetRevenueCatStatusQuery(undefined, {
            skip: !hasAccessToken
        })
    const isRevenueCatConnected = statusData?.is_connected ?? false
    const [disconnectRevenueCat] = useDisconnectRevenueCatMutation()

    const [isRevenueCatProcessing, setIsRevenueCatProcessing] = useState(false)
    const [revenueCatAction, setRevenueCatAction] =
        useState<RevenueCatAction>(null)

    const handleRevenueCatConnect = async () => {
        if (isRevenueCatProcessing) return

        setIsRevenueCatProcessing(true)
        setRevenueCatAction('connect')
        try {
            const { auth_url } = await connectorService.getRevenueCatAuthUrl()
            const { code, state } = await connectorService.openAuthPopup(
                auth_url,
                t('connectors.revenuecat.authPopupTitle')
            )
            const result = await connectorService.handleRevenueCatCallback(
                code,
                state
            )

            if (!result.success) {
                throw new Error(
                    result.message ||
                        t('connectors.revenuecat.errors.connectFailed')
                )
            }

            dispatch(connectorApi.util.invalidateTags(['RevenueCatStatus']))
            toast.success(t('connectors.revenuecat.toasts.connected'))
        } catch (error) {
            console.error('Failed to connect RevenueCat', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : t('connectors.revenuecat.errors.connectFailed')
            )
        } finally {
            setIsRevenueCatProcessing(false)
            setRevenueCatAction(null)
        }
    }

    const handleRevenueCatDisconnect = async () => {
        if (isRevenueCatProcessing) return

        setIsRevenueCatProcessing(true)
        setRevenueCatAction('disconnect')
        try {
            const result = await disconnectRevenueCat().unwrap()

            if (!result.success) {
                throw new Error(
                    result.message ||
                        t('connectors.revenuecat.errors.disconnectFailed')
                )
            }

            toast.success(t('connectors.revenuecat.toasts.disconnected'))
        } catch (error) {
            console.error('Failed to disconnect RevenueCat', error)
            toast.error(
                error instanceof Error
                    ? error.message
                    : t('connectors.revenuecat.errors.disconnectFailed')
            )
        } finally {
            setIsRevenueCatProcessing(false)
            setRevenueCatAction(null)
        }
    }

    const revenueCatButtonLabel = (() => {
        if (isRevenueCatLoading) return t('connectors.status.checking')
        if (isRevenueCatProcessing) {
            return revenueCatAction === 'disconnect'
                ? t('connectors.status.disconnecting')
                : t('connectors.status.connecting')
        }
        return isRevenueCatConnected
            ? t('connectors.revenuecat.disconnect')
            : t('connectors.revenuecat.connect')
    })()

    if (variant === 'project') {
        return (
            <div className="rounded-2xl border border-black/10 bg-firefly/5 p-5 dark:border-white/10 dark:bg-sky-blue-2/5">
                <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                    <div className="flex items-center gap-4">
                        <img
                            src="/images/revenuecat.svg"
                            alt="RevenueCat"
                            className="size-12"
                        />
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <p className="text-base font-semibold">
                                    {t('connectors.revenuecat.title')}
                                </p>
                                <Badge
                                    variant="outline"
                                    className={cn(
                                        'border-black/10 bg-white/70 text-black dark:border-white/10 dark:bg-white/5 dark:text-white',
                                        isRevenueCatConnected &&
                                            'border-emerald-600/30 text-emerald-700 dark:text-emerald-400'
                                    )}
                                >
                                    {isRevenueCatConnected
                                        ? t('connectors.revenuecat.connected')
                                        : t(
                                              'project.integrations.status.notConnected'
                                          )}
                                </Badge>
                            </div>
                            <p className="text-sm text-black/65 dark:text-white/65">
                                {t('connectors.revenuecat.description')}
                            </p>
                        </div>
                    </div>
                    <Button
                        className={cn(
                            'rounded-full px-4',
                            isRevenueCatConnected
                                ? 'bg-red-600 text-white hover:bg-red-600/90 dark:bg-red-500 dark:text-white'
                                : 'bg-firefly text-sky-blue-2 hover:bg-firefly/90 dark:bg-sky-blue dark:text-black dark:hover:bg-sky-blue/90'
                        )}
                        disabled={isRevenueCatLoading || isRevenueCatProcessing}
                        onClick={
                            isRevenueCatConnected
                                ? handleRevenueCatDisconnect
                                : handleRevenueCatConnect
                        }
                    >
                        {revenueCatButtonLabel}
                    </Button>
                </div>
            </div>
        )
    }

    return (
        <div className="flex items-center justify-between">
            <div className="space-y-1">
                <p className="text-sm">{t('connectors.revenuecat.title')}</p>
                <p className="text-xs text-black/60 dark:text-white/60">
                    {t('connectors.revenuecat.description')}
                </p>
            </div>
            <Button
                className={cn(
                    'underline p-0 h-auto text-black/[0.56] dark:text-white/[0.56]',
                    isRevenueCatConnected && 'text-red-600 dark:text-red-400'
                )}
                disabled={isRevenueCatLoading || isRevenueCatProcessing}
                onClick={
                    isRevenueCatConnected
                        ? handleRevenueCatDisconnect
                        : handleRevenueCatConnect
                }
            >
                {revenueCatButtonLabel}
            </Button>
        </div>
    )
}
