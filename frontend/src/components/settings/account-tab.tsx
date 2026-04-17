import { useNavigate } from 'react-router'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import dayjs from 'dayjs'
import { useTranslation } from 'react-i18next'

import { useAppSelector } from '@/state/store'
import {
    selectSubscriptionCurrentPeriodEnd,
    selectSubscriptionPlan,
    selectSubscriptionStatus,
    selectUser
} from '@/state/slice/user'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { getFirstCharacters } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/contexts/auth-context'
import { billingService } from '@/services/billing.service'
import { userService } from '@/services/user.service'
import { SubscriptionPlan } from '@/typings/subscription'
import { SUBSCRIPTION_PLANS } from '@/constants/subscription'
// Hidden: GitHub and Google Drive connections
// import { GoogleDriveConnection } from './google-drive-connection'
// import { GitHubConnection } from './github-connection'
import { SupabaseConnection } from '@/components/project/supabase-connection'
import { RevenueCatConnection } from './revenuecat-connection'
import { SHOW_BILLING_UI } from '@/constants/features'
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle
} from '@/components/ui/alert-dialog'

const AccountTab = () => {
    const { t } = useTranslation()
    const user = useAppSelector(selectUser)
    const { logout } = useAuth()
    const navigate = useNavigate()
    const [isManaging, setIsManaging] = useState(false)
    const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false)
    const [isDeleting, setIsDeleting] = useState(false)

    const status = useAppSelector(selectSubscriptionStatus)
    const currentPeriodEnd = useAppSelector(selectSubscriptionCurrentPeriodEnd)
    const plan = useAppSelector(selectSubscriptionPlan) ?? SubscriptionPlan.Free

    const formattedPeriodEnd = useMemo(() => {
        if (!currentPeriodEnd || (status !== 'active' && status !== 'paid'))
            return t('common.notAvailable')

        const parsed = dayjs(currentPeriodEnd)
        return parsed.isValid()
            ? parsed.format('MMMM D, YYYY')
            : t('common.notAvailable')
    }, [currentPeriodEnd, status, t])

    const handleLogout = () => {
        logout()
        navigate('/login')
    }

    const handleManageSubscription = async () => {
        if (isManaging) return

        try {
            setIsManaging(true)
            const { url } = await billingService.createPortalSession({
                returnUrl: window.location.href
            })
            if (!url) {
                toast.error(t('settings.account.stripePortalError'))
                return
            }

            window.open(url)
        } catch (error) {
            console.error('Failed to create Stripe portal session', error)
            toast.error(t('settings.account.stripePortalError'))
        } finally {
            setIsManaging(false)
        }
    }

    const handleDeleteAccount = async () => {
        if (isDeleting) return

        try {
            setIsDeleting(true)
            await userService.deleteAccount()
            toast.success(t('settings.account.accountDeleted'))
            logout()
            navigate('/login')
        } catch (error) {
            console.error('Failed to delete account', error)
            toast.error(t('settings.account.deleteAccountError'))
        } finally {
            setIsDeleting(false)
            setIsDeleteDialogOpen(false)
        }
    }

    return (
        <div className="space-y-6 md:pt-2">
            <div className="flex items-center gap-4 mb-6">
                <Avatar className="size-14">
                    <AvatarImage src={user?.avatar} />
                    <AvatarFallback>
                        {user?.first_name
                            ? getFirstCharacters(
                                  `${user?.first_name} ${user?.last_name}`
                              )
                            : `II`}
                    </AvatarFallback>
                </Avatar>
                <div className="space-y-1">
                    <p className="text-[18px] font-semibold">{`${user?.first_name} ${user?.last_name}`}</p>
                    <p className="text-sm">{user?.email}</p>
                </div>
            </div>

            <div className="space-y-4 pt-4 md:pt-6 border-t border-black/30 dark:border-white/30">
                <h2 className="text-[18px] font-semibold mb-4">
                    {t('settings.account.linkedAccounts')}
                </h2>
                <SupabaseConnection variant="settings" />
                <RevenueCatConnection />
            </div>

            {SHOW_BILLING_UI && plan !== SubscriptionPlan.Free && (
                <div className="pt-4 md:pt-6 border-t border-black/30 dark:border-white/30">
                    <h2 className="text-[18px] font-semibold mb-2">
                        {t('settings.account.paymentInvoices')}
                    </h2>
                    <div className="space-y-4">
                        <div className="flex items-center gap-x-4">
                            <Button
                                size="xl"
                                className="bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black font-semibold w-[247px]"
                                onClick={handleManageSubscription}
                            >
                                {t('common.manage')}
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {SHOW_BILLING_UI && plan !== SubscriptionPlan.Free && (
                <div className="pt-4 md:pt-6 border-t border-black/30 dark:border-white/30">
                    <h2 className="text-[18px] font-semibold mb-2">
                        {t('settings.account.planTitle', {
                            plan: SUBSCRIPTION_PLANS[plan].name
                        })}
                    </h2>
                    <div className="space-y-4">
                        <p className="text-sm text-black dark:text-white">
                            {t('settings.account.planRenewal', {
                                date: formattedPeriodEnd
                            })}
                        </p>
                        <div className="flex items-center gap-x-4">
                            <Button
                                size="xl"
                                className="bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black font-semibold w-[247px]"
                                onClick={handleManageSubscription}
                            >
                                {t('common.manage')}
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            <div className="pt-4 md:py-6 border-t border-black/30 dark:border-white/30">
                <h2 className="text-[18px] font-semibold mb-4">
                    {t('settings.account.security')}
                </h2>
                <div className="flex items-center gap-x-4">
                    <Button
                        size="xl"
                        className="bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black font-semibold flex-1 md:w-[247px]"
                        onClick={handleLogout}
                    >
                        {t('auth.signOut')}
                    </Button>

                    <Button
                        size="xl"
                        variant="outline"
                        className="text-white border-red-2 !bg-red-2 flex-1 md:w-[247px]"
                        onClick={() => setIsDeleteDialogOpen(true)}
                    >
                        {t('settings.account.deleteAccount')}
                    </Button>
                </div>
            </div>

            <AlertDialog
                open={isDeleteDialogOpen}
                onOpenChange={setIsDeleteDialogOpen}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>
                            {t('settings.account.deleteAccountTitle')}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            {t('settings.account.deleteAccountConfirmation')}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>
                            {t('common.cancel')}
                        </AlertDialogCancel>
                        <AlertDialogAction
                            onClick={handleDeleteAccount}
                            className="bg-red-2 hover:bg-red-2 text-white"
                            disabled={isDeleting}
                        >
                            {isDeleting
                                ? t('settings.account.deleting')
                                : t('settings.account.deleteAccount')}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    )
}

export default AccountTab
