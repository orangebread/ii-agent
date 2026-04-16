import { useGoogleLogin } from '@react-oauth/google'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'

interface GoogleAuthButtonProps {
    className?: string
    label: string
    onAuthCode: (code: string) => Promise<void>
}

export function GoogleAuthButton({
    className,
    label,
    onAuthCode
}: GoogleAuthButtonProps) {
    const googleLogin = useGoogleLogin({
        flow: 'auth-code',
        onSuccess: async (codeResponse) => {
            try {
                await onAuthCode(codeResponse.code)
            } catch (error: unknown) {
                const apiError = error as {
                    response?: { data?: { detail?: string } }
                }
                const detail = apiError.response?.data?.detail
                toast.error(
                    typeof detail === 'string'
                        ? detail
                        : 'Failed to sign in with Google'
                )
            }
        },
        onError: (errorResponse) => {
            console.error('Google login failed:', errorResponse)
            toast.error('Failed to sign in with Google')
        }
    })

    return (
        <Button size="xl" onClick={() => googleLogin()} className={className}>
            <Icon name="google" className="size-[22px]" />
            {label}
        </Button>
    )
}
