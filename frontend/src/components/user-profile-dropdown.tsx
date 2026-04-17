import { useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'

import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar'
import { getFirstCharacters } from '@/lib/utils'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from './ui/dropdown-menu'
import { useAuth } from '@/contexts/auth-context'
import { selectSubscriptionPlan, selectUser } from '@/state/slice/user'
import { useAppSelector } from '@/state/store'
import { Icon } from './ui/icon'
import { SUBSCRIPTION_PLANS } from '@/constants/subscription'
import { SHOW_BILLING_UI } from '@/constants/features'

interface UserProfileDropdownProps {
    avatarClassName?: string
    showPlan?: boolean
    children?: React.ReactNode
}

const UserProfileDropdown = ({
    avatarClassName,
    showPlan = false,
    children
}: UserProfileDropdownProps) => {
    const navigate = useNavigate()
    const { t } = useTranslation()
    const { logout } = useAuth()
    const user = useAppSelector(selectUser)
    const subscriptionPlan = useAppSelector(selectSubscriptionPlan)

    const handleLogout = () => {
        logout()
        navigate('/login')
    }

    const handleGetHelp = () => {
        window.open('https://discord.com/invite/intelligentinternet', '_blank')
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <div className="flex gap-x-2 items-center">
                    <Avatar
                        className={`size-10 cursor-pointer hover:opacity-80 transition-opacity ${avatarClassName}`}
                    >
                        <AvatarImage src={user?.avatar} />
                        <AvatarFallback>
                            {user?.first_name
                                ? getFirstCharacters(
                                      `${user?.first_name} ${user?.last_name}`
                                  )
                                : `II`}
                        </AvatarFallback>
                    </Avatar>
                    {children}
                    {showPlan && SHOW_BILLING_UI && (
                        <div className="flex flex-col">
                            <p>{`${user?.first_name} ${user?.last_name}`}</p>
                            <p className="text-xs text-black dark:text-grey-6 flex-1">
                                {subscriptionPlan
                                    ? t('credit.planLabel', {
                                          plan: SUBSCRIPTION_PLANS[
                                              subscriptionPlan
                                          ]?.name
                                      })
                                    : t('credit.freePlan')}
                            </p>
                        </div>
                    )}
                </div>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[189px] space-y-4">
                <DropdownMenuItem className="flex items-center gap-2 p-0">
                    <Avatar className="size-10">
                        <AvatarImage src={user?.avatar} />
                        <AvatarFallback className="text-xs">
                            {user?.first_name
                                ? getFirstCharacters(
                                      `${user?.first_name} ${user?.last_name}`
                                  )
                                : `II`}
                        </AvatarFallback>
                    </Avatar>
                    <div className="flex flex-col min-w-0">
                        <span className="font-semibold text-sm">
                            {user?.first_name} {user?.last_name}
                        </span>
                        <span className="text-xs truncate">{user?.email}</span>
                    </div>
                </DropdownMenuItem>
                <DropdownMenuItem
                    className="flex items-center gap-[6px] p-0"
                    onClick={() => navigate('/settings/account')}
                >
                    <Icon name="user-2" className="size-4 fill-black" />
                    <span>{t('settings.tabs.account')}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                    className="flex items-center gap-[6px] p-0"
                    onClick={() => navigate('/settings/general')}
                >
                    <Icon name="globe" className="size-4 stroke-black" />
                    <span>{t('settings.general.language')}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                    className="flex items-center gap-[6px] p-0"
                    onClick={() => navigate('/settings/usage')}
                >
                    <Icon name="dashboard-2" className="size-4 fill-black" />
                    <span>{t('settings.tabs.usage')}</span>
                </DropdownMenuItem>
                {SHOW_BILLING_UI && (
                    <DropdownMenuItem
                        className="flex items-center gap-[6px] p-0"
                        onClick={() => navigate('/settings/subscription')}
                    >
                        <Icon
                            name="dollar-circle"
                            className="size-4 fill-black"
                        />
                        <span>{t('settings.tabs.subscription')}</span>
                    </DropdownMenuItem>
                )}
                {SHOW_BILLING_UI && (
                    <DropdownMenuItem
                        className="flex items-center gap-[6px] p-0"
                        onClick={() => navigate('/settings/account')}
                    >
                        <Icon name="receipt" className="size-4 fill-black" />
                        <span>{t('settings.account.paymentInvoices')}</span>
                    </DropdownMenuItem>
                )}
                <DropdownMenuSeparator className="my-3" />
                <DropdownMenuItem
                    className="flex items-center gap-[6px] p-0"
                    onClick={() => navigate('/settings/general')}
                >
                    <Icon name="setting-2" className="size-4 fill-black" />
                    <span>{t('settings.title')}</span>
                </DropdownMenuItem>

                <DropdownMenuItem
                    className="flex items-center justify-between gap-[6px] p-0"
                    onClick={handleGetHelp}
                >
                    <div className="flex items-center gap-[6px]">
                        <Icon name="help" className="size-4 stroke-black" />
                        <span>{t('userMenu.getHelp')}</span>
                    </div>
                    <Icon name="arrow-right-2" className="size-4 fill-black" />
                </DropdownMenuItem>
                <DropdownMenuSeparator className="my-3" />
                <DropdownMenuItem
                    className="flex items-center gap-[6px] text-red-2 p-0"
                    variant="destructive"
                    onClick={handleLogout}
                >
                    <Icon name="logout" className="size-4 fill-red-2" />
                    <span>{t('auth.signOut')}</span>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export default UserProfileDropdown
