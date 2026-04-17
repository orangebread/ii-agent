import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { SUBSCRIPTION_PLANS } from '@/constants/subscription'
import { useAppSelector, useGetCreditBalanceQuery } from '@/state'
import { selectSubscriptionPlan, selectUser } from '@/state/slice/user'
import { SubscriptionPlan } from '@/typings/subscription'
import CreditTooltip from './credit-tooltip'
import { Icon } from './ui/icon'
import UserProfileDropdown from './user-profile-dropdown'
import { IS_LOCAL_DEPLOYMENT } from '@/constants/features'

const Credit = () => {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const user = useAppSelector(selectUser)
    const subscriptionPlan = useAppSelector(selectSubscriptionPlan)

    // Use RTK Query hook instead of Redux selectors
    const { data: balanceData, isLoading } = useGetCreditBalanceQuery(
        undefined,
        { skip: IS_LOCAL_DEPLOYMENT }
    )

    const availableCredit = balanceData?.credits || 0
    const bonusCredit = balanceData?.bonus_credits || 0

    const formatCredit = (value: number) => {
        const rounded = Math.round(value)
        return (rounded === 0 ? 0 : rounded).toLocaleString('en-US')
    }

    const handleGotoSubscription = () => {
        navigate('/settings/subscription')
    }

    const totalCredit = useMemo(() => {
        return availableCredit + bonusCredit
    }, [availableCredit, bonusCredit])

    const isProPlan = useMemo(
        () => subscriptionPlan === SubscriptionPlan.Pro,
        [subscriptionPlan]
    )

    if (IS_LOCAL_DEPLOYMENT) {
        return (
            <div className="hidden md:flex flex-col items-start group-data-[collapsible=icon]:items-center gap-y-4 p-6 pb-8 border-t border-grey-2/30 dark:border-white/30 group-data-[collapsible=icon]:border-none group-data-[collapsible=icon]:gap-y-6">
                <Link
                    to="/settings/usage"
                    className="flex items-center gap-x-2 rounded-full border border-grey-2/40 px-3 py-1.5 text-sm text-black dark:text-white group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:border-none"
                >
                    <Icon
                        name="dashboard-2"
                        className="size-5 fill-black dark:fill-white"
                    />
                    <span className="group-data-[collapsible=icon]:hidden">
                        {t('settings.tabs.usage')}
                    </span>
                </Link>

                <UserProfileDropdown>
                    <p className="text-sm cursor-pointer group-data-[collapsible=icon]:hidden">{`${user?.first_name} ${user?.last_name}`}</p>
                </UserProfileDropdown>
            </div>
        )
    }

    if (isLoading) return null

    return (
        <div className="hidden md:flex flex-col items-start group-data-[collapsible=icon]:items-center gap-y-4 p-6 pb-8 border-t border-grey-2/30 dark:border-white/30 group-data-[collapsible=icon]:border-none group-data-[collapsible=icon]:gap-y-6">
            {!isProPlan && (
                <button
                    onClick={handleGotoSubscription}
                    className="cursor-pointer group-data-[collapsible=icon]:hidden text-xs font-semibold text-sky-blue-2 dark:text-black bg-charcoal dark:bg-sky-blue px-3 h-6 rounded-[30px] flex items-center"
                >
                    {t('upgrade.title')}
                </button>
            )}

            <CreditTooltip credits={availableCredit} bonusCredits={bonusCredit}>
                <div className="cursor-pointer flex gap-x-2">
                    <Icon
                        name="coin"
                        className="fill-black dark:fill-white size-5"
                    />
                    <div className="group-data-[collapsible=icon]:hidden">
                        <div className="flex items-baseline gap-1">
                            <Link
                                to="/settings/usage"
                                className="font-bold text-charcoal dark:text-yellow hover:underline text-base"
                            >
                                {formatCredit(totalCredit)}
                            </Link>
                            {/* <span className="text-black/30 dark:text-white/30 text-base">{`/ ${formatCredit(totalCredit)}`}</span> */}
                        </div>
                        <p className="text-black dark:text-white text-xs">
                            {subscriptionPlan
                                ? t('credit.planLabel', {
                                      plan: SUBSCRIPTION_PLANS[subscriptionPlan]
                                          ?.name
                                  })
                                : t('credit.freePlan')}
                        </p>
                    </div>
                </div>
            </CreditTooltip>

            <UserProfileDropdown>
                <p className="text-sm cursor-pointer group-data-[collapsible=icon]:hidden">{`${user?.first_name} ${user?.last_name}`}</p>
            </UserProfileDropdown>
        </div>
    )
}

export default Credit
