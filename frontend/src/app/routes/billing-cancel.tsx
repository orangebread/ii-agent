import Lottie from 'lottie-react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import Cancel from '@/assets/cancel.json'
import { IS_LOCAL_DEPLOYMENT } from '@/constants/features'

const BillingCancel = () => {
    const navigate = useNavigate()

    useEffect(() => {
        toast.info(
            IS_LOCAL_DEPLOYMENT
                ? 'Billing is disabled in local mode.'
                : 'Checkout cancelled. No changes were made to your subscription.'
        )

        const timer = setTimeout(() => {
            navigate(
                IS_LOCAL_DEPLOYMENT
                    ? '/settings/usage'
                    : '/settings/subscription',
                { replace: true }
            )
        }, 2000)

        return () => clearTimeout(timer)
    }, [navigate])

    return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6 text-center">
            <div className="max-w-md space-y-4">
                <div className="flex justify-center">
                    <Lottie
                        className="w-30"
                        animationData={Cancel}
                        loop={true}
                    />
                </div>
                <h1 className="text-2xl font-semibold text-firefly dark:text-white">
                    {IS_LOCAL_DEPLOYMENT
                        ? 'Billing unavailable'
                        : 'Checkout Cancelled'}
                </h1>
                <p className="text-sm text-slate dark:text-white/70">
                    {IS_LOCAL_DEPLOYMENT
                        ? 'This local build does not expose subscription checkout.'
                        : 'You can resume your checkout anytime from the subscription page.'}
                </p>
                <p className="text-xs text-slate/70 dark:text-white/50">
                    {IS_LOCAL_DEPLOYMENT
                        ? 'Redirecting to usage settings...'
                        : 'Redirecting to subscription settings...'}
                </p>
            </div>
        </div>
    )
}

export const Component = BillingCancel
