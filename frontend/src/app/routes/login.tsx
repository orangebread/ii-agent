import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useTranslation } from 'react-i18next'

import { useAuth } from '@/contexts/auth-context'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import { Form, FormControl, FormField, FormItem } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { authService } from '@/services/auth.service'
import { toast } from 'sonner'
import { useIsSageTheme } from '@/hooks/use-is-sage-theme'
import { GoogleAuthButton } from '@/components/auth/google-auth-button'
import { isGoogleOAuthConfigured } from '@/lib/google-oauth'
import type {
    AuthTokenResponse,
    OpenAIDevicePollResponse,
    OpenAIDeviceStartResponse
} from '@/typings/auth'

interface DeviceAuthState {
    loginId: string
    verificationUrl: string
    userCode: string
    intervalSeconds: number
}

interface OpenAIConnectionState {
    readyToContinue: boolean
    pendingConnectId: string
}

export function LoginPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { loginWithAuthCode, completeTokenLogin } = useAuth()
    const isSage = useIsSageTheme()

    const FormSchema = useMemo(
        () =>
            z.object({
                email: z.email({
                    error: t('auth.validation.invalidEmail')
                }),
                password: z
                    .string({
                        error: t('auth.validation.passwordRequired')
                    })
                    .min(6, {
                        message: t('auth.validation.passwordMinLength')
                    })
            }),
        [t]
    )

    const form = useForm<z.infer<typeof FormSchema>>({
        resolver: zodResolver(FormSchema),
        defaultValues: {
            email: '',
            password: ''
        }
    })

    const googleOAuthEnabled = isGoogleOAuthConfigured()

    const apiBaseUrl = useMemo(
        () => import.meta.env.VITE_API_URL || 'http://localhost:8000',
        []
    )
    const apiOrigin = useMemo(() => {
        try {
            return new URL(apiBaseUrl).origin
        } catch (error) {
            console.error('Invalid API base URL:', error)
            return apiBaseUrl
        }
    }, [apiBaseUrl])

    const authHandledRef = useRef(false)
    const [deviceAuth, setDeviceAuth] = useState<DeviceAuthState | null>(null)
    const [isConnectingOpenAI, setIsConnectingOpenAI] = useState(false)
    const [iiOAuthAvailable, setIiOAuthAvailable] = useState<boolean | null>(
        null
    )
    const [devAuthBypassEnabled, setDevAuthBypassEnabled] = useState(false)
    const [openAIConnection, setOpenAIConnection] =
        useState<OpenAIConnectionState | null>(null)

    const loadAuthProviders = useCallback(async () => {
        try {
            const providers = await authService.getAuthProviders()
            setIiOAuthAvailable(providers.ii_oauth_available)
            setDevAuthBypassEnabled(providers.dev_auth_bypass_enabled)
            return providers
        } catch (error) {
            console.error('Failed to load auth providers:', error)
            setIiOAuthAvailable((current) => current)
            setDevAuthBypassEnabled((current) => current)
            return null
        }
    }, [])

    const iiContinueAvailable =
        devAuthBypassEnabled || iiOAuthAvailable !== false

    const handleAuthSuccess = useCallback(
        async (payload: AuthTokenResponse | null | undefined) => {
            if (!payload || typeof payload.access_token !== 'string') {
                authHandledRef.current = false
                return
            }

            if (authHandledRef.current) {
                return
            }
            authHandledRef.current = true

            try {
                await completeTokenLogin(payload.access_token)
                navigate('/')
            } catch (error) {
                console.error('Failed to finalize II login:', error)
                authHandledRef.current = false
            }
        },
        [completeTokenLogin, navigate]
    )

    useEffect(() => {
        void loadAuthProviders()
    }, [loadAuthProviders])

    useEffect(() => {
        const handler = (event: MessageEvent) => {
            if (event.origin !== apiOrigin) {
                return
            }

            const data = event.data as {
                type?: string
                payload?: AuthTokenResponse
            }

            if (!data || data.type !== 'ii-auth-success') {
                return
            }

            void handleAuthSuccess(data.payload)
        }

        window.addEventListener('message', handler)
        return () => window.removeEventListener('message', handler)
    }, [apiOrigin, handleAuthSuccess])

    useEffect(() => {
        const hash = window.location.hash
        if (!hash || !hash.includes('ii-auth=')) {
            return
        }

        const params = new URLSearchParams(hash.slice(1))
        const encoded = params.get('ii-auth')
        params.delete('ii-auth')

        const cleanHash = params.toString()
        const cleanUrl = `${window.location.pathname}${window.location.search}${cleanHash ? `#${cleanHash}` : ''}`
        window.history.replaceState(null, '', cleanUrl)

        if (!encoded) {
            return
        }

        try {
            const payload = JSON.parse(
                decodeURIComponent(encoded)
            ) as AuthTokenResponse
            void handleAuthSuccess(payload)
        } catch (error) {
            console.error('Failed to parse II auth payload from hash:', error)
            authHandledRef.current = false
        }
    }, [handleAuthSuccess])

    const loginWithII = useCallback(() => {
        authHandledRef.current = false

        const url = new URL('/auth/oauth/ii/login', apiBaseUrl)
        url.searchParams.set('return_to', window.location.href)
        if (openAIConnection?.pendingConnectId) {
            url.searchParams.set(
                'openai_pending',
                openAIConnection.pendingConnectId
            )
        }

        const width = 500
        const height = 700
        const left = window.screenX + (window.outerWidth - width) / 2
        const top = window.screenY + (window.outerHeight - height) / 2

        const features = [
            `width=${Math.max(400, Math.floor(width))}`,
            `height=${Math.max(500, Math.floor(height))}`,
            `left=${Math.max(0, Math.floor(left))}`,
            `top=${Math.max(0, Math.floor(top))}`,
            'resizable=yes',
            'scrollbars=yes'
        ].join(',')

        const popup = window.open(url.toString(), 'ii-login', features)

        if (!popup) {
            window.location.href = url.toString()
            return
        }

        popup.focus()
    }, [apiBaseUrl, openAIConnection])

    const onSubmit = async (data: z.infer<typeof FormSchema>) => {
        console.log(data)
    }

    const hideSigninWithPassword = true

    const handleConnectOpenAI = useCallback(async () => {
        try {
            setIsConnectingOpenAI(true)
            setOpenAIConnection(null)
            const response: OpenAIDeviceStartResponse =
                await authService.startOpenAIDeviceLogin({
                    model: 'gpt-5',
                    model_reasoning_effort: 'medium',
                    search: false
                })

            setDeviceAuth({
                loginId: response.login_id,
                verificationUrl: response.verification_url,
                userCode: response.user_code,
                intervalSeconds: response.interval_seconds
            })

            window.open(
                response.verification_url,
                '_blank',
                'noopener,noreferrer'
            )
        } catch (error: unknown) {
            console.error('Error starting OpenAI device auth:', error)
            const apiError = error as {
                response?: { data?: { detail?: string } }
            }
            toast.error(
                apiError.response?.data?.detail ||
                    'Failed to start OpenAI sign-in'
            )
        } finally {
            setIsConnectingOpenAI(false)
        }
    }, [])

    useEffect(() => {
        if (!deviceAuth) {
            return
        }

        let isCancelled = false

        const poll = async () => {
            try {
                const response: OpenAIDevicePollResponse =
                    await authService.pollOpenAIDeviceLogin({
                        login_id: deviceAuth.loginId
                    })

                if (isCancelled || response.status === 'pending') {
                    return
                }

                if (response.status === 'completed') {
                    if (!response.pending_connect_id) {
                        toast.error(
                            'OpenAI connected, but the handoff to II-Agent was missing. Start again.'
                        )
                        setDeviceAuth(null)
                        setOpenAIConnection(null)
                        return
                    }
                    await loadAuthProviders()
                    setDeviceAuth(null)
                    setOpenAIConnection({
                        readyToContinue: response.continue_with_ii,
                        pendingConnectId: response.pending_connect_id
                    })
                    toast.success(
                        'OpenAI connected. Finish II-Agent sign-in to enter the app.'
                    )
                    return
                }

                toast.error(
                    response.error || 'OpenAI sign-in failed. Start again.'
                )
                setDeviceAuth(null)
                setOpenAIConnection(null)
            } catch (error: unknown) {
                if (isCancelled) {
                    return
                }
                console.error('Error polling OpenAI device auth:', error)
                const apiError = error as {
                    response?: { data?: { detail?: string } }
                }
                toast.error(
                    apiError.response?.data?.detail ||
                        'OpenAI sign-in failed. Start again.'
                )
                setDeviceAuth(null)
                setOpenAIConnection(null)
            }
        }

        const timer = window.setInterval(
            poll,
            Math.max(deviceAuth.intervalSeconds, 3) * 1000
        )
        void poll()

        return () => {
            isCancelled = true
            window.clearInterval(timer)
        }
    }, [deviceAuth, loadAuthProviders])

    const handleGoogleAuthCode = useCallback(
        async (authCode: string) => {
            try {
                await loginWithAuthCode(authCode)
                navigate('/')
            } catch (error: unknown) {
                const apiError = error as {
                    response?: { data?: { detail?: string } }
                }
                const errorMessage =
                    typeof apiError?.response?.data?.detail === 'string'
                        ? apiError.response.data.detail
                        : t('auth.loginFailed')
                if (errorMessage?.includes('beta')) {
                    toast.info(errorMessage)
                } else {
                    toast.error(errorMessage)
                }
                throw error
            }
        },
        [loginWithAuthCode, navigate, t]
    )

    return (
        <div className="flex flex-col items-center justify-center w-full h-full">
            <h1 className="text-[25px] md:text-[32px] font-semibold text-firefly dark:text-sky-blue">
                {t('auth.welcomeTitle', {
                    appName: isSage ? 'SAGE' : t('common.appName')
                })}
            </h1>
            <p className="text-[20px] md:text-[28px] text-firefly dark:text-sky-blue mb-12">
                {t('auth.welcomeSubtitle')}
            </p>

            <div className="flex flex-col w-full justify-center max-w-[510px]">
                <div className={`${hideSigninWithPassword ? 'hidden' : ''}`}>
                    <Form {...form}>
                        <form
                            onSubmit={form.handleSubmit(onSubmit)}
                            className="flex flex-col gap-10"
                        >
                            <div className="space-y-6">
                                <FormField
                                    control={form.control}
                                    name="email"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormControl>
                                                <div className="space-y-2 relative">
                                                    <Icon
                                                        name="email"
                                                        className="absolute top-3 left-4 fill-black dark:fill-white"
                                                    />
                                                    <Input
                                                        id="email"
                                                        className="pl-[56px]"
                                                        type="text"
                                                        placeholder={t(
                                                            'auth.emailPlaceholder'
                                                        )}
                                                        {...field}
                                                    />
                                                </div>
                                            </FormControl>
                                        </FormItem>
                                    )}
                                />
                                <div className="space-y-4 text-right">
                                    <FormField
                                        control={form.control}
                                        name="password"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormControl>
                                                    <div className="space-y-2 relative">
                                                        <Icon
                                                            name="key"
                                                            className="absolute top-3 left-4 fill-black dark:fill-white"
                                                        />
                                                        <Input
                                                            id="password"
                                                            className="pl-[56px]"
                                                            type="password"
                                                            placeholder={t(
                                                                'auth.passwordPlaceholder'
                                                            )}
                                                            {...field}
                                                        />
                                                    </div>
                                                </FormControl>
                                            </FormItem>
                                        )}
                                    />
                                    <Link
                                        to="/forgot-password"
                                        className="text-sm underline"
                                    >
                                        {t('auth.forgotPassword')}
                                    </Link>
                                </div>
                            </div>
                            <div className="w-full flex justify-center">
                                <Button
                                    type="submit"
                                    size="xl"
                                    className="bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black font-semibold w-full max-w-[247px]"
                                    disabled={!form.formState.isValid}
                                >
                                    {t('auth.signIn')}
                                </Button>
                            </div>
                        </form>
                    </Form>
                    <div className="flex justify-center items-center gap-2 text-black dark:text-white text-sm mt-8">
                        <span>{t('auth.noAccount')}</span>
                        <Link
                            to="/signup"
                            className="text-black dark:text-white text-sm font-semibold"
                        >
                            {t('auth.signUp')}
                        </Link>
                    </div>
                    <div className="flex w-full items-center gap-4 my-10">
                        <p className="flex-1 bg-black/[0.31] dark:bg-white/[0.31] h-[1px]"></p>
                        <span className="text-sm text-black dark:text-white font-semibold">
                            {t('common.or')}
                        </span>
                        <p className="flex-1 bg-black/[0.31] dark:bg-white/[0.31] h-[1px]"></p>
                    </div>
                </div>
                <Button
                    size="xl"
                    onClick={handleConnectOpenAI}
                    disabled={isConnectingOpenAI}
                    className="w-full bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black font-semibold shadow-btn"
                >
                    {isConnectingOpenAI
                        ? 'Starting OpenAI sign-in...'
                        : 'Continue with OpenAI'}
                </Button>
                {deviceAuth ? (
                    <div className="mt-4 space-y-4 rounded-3xl border border-sky-blue/30 bg-sky-blue/10 p-5 dark:border-sky-blue-2/30 dark:bg-sky-blue-2/10">
                        <div>
                            <p className="text-sm font-semibold text-firefly dark:text-white">
                                Finish sign-in in your browser
                            </p>
                            <p className="mt-1 text-sm text-firefly/75 dark:text-white/70">
                                Open the verification page and enter this
                                one-time code. After approval, return here and
                                continue through the normal II-Agent sign-in.
                            </p>
                        </div>
                        <div className="rounded-2xl bg-white px-4 py-3 dark:bg-white/5">
                            <p className="text-xs uppercase tracking-wide text-firefly/55 dark:text-white/55">
                                Code
                            </p>
                            <p className="text-2xl font-semibold tracking-[0.16em] text-firefly dark:text-white">
                                {deviceAuth.userCode}
                            </p>
                        </div>
                        <div className="flex flex-col gap-3 md:flex-row">
                            <Button
                                type="button"
                                className="flex-1 bg-white text-black font-semibold shadow-btn"
                                onClick={() =>
                                    window.open(
                                        deviceAuth.verificationUrl,
                                        '_blank',
                                        'noopener,noreferrer'
                                    )
                                }
                            >
                                Open Verification Page
                            </Button>
                            <Button
                                type="button"
                                variant="outline"
                                className="flex-1"
                                onClick={() => setDeviceAuth(null)}
                            >
                                Cancel
                            </Button>
                        </div>
                    </div>
                ) : null}
                {openAIConnection?.readyToContinue ? (
                    <div className="mt-4 space-y-4 rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-5 dark:border-emerald-400/30 dark:bg-emerald-400/10">
                        <div>
                            <p className="text-sm font-semibold text-firefly dark:text-white">
                                OpenAI is staged successfully
                            </p>
                            <p className="mt-1 text-sm text-firefly/75 dark:text-white/70">
                                Your Codex connection is held server-side for
                                this browser session. Finish II-Agent sign-in
                                now and we will attach it during callback.
                            </p>
                        </div>
                        {iiContinueAvailable ? (
                            <Button
                                size="xl"
                                onClick={loginWithII}
                                className="w-full bg-white text-black font-semibold shadow-btn"
                            >
                                <img
                                    src="/images/logo-charcoal.png"
                                    alt="logo"
                                    className="size-[22px]"
                                />
                                Continue with II
                            </Button>
                        ) : (
                            <Button
                                size="xl"
                                disabled
                                className="w-full bg-white/70 text-black/60 font-semibold shadow-btn cursor-not-allowed"
                            >
                                <img
                                    src="/images/logo-charcoal.png"
                                    alt="logo"
                                    className="size-[22px] opacity-60"
                                />
                                Continue with II
                            </Button>
                        )}
                    </div>
                ) : null}
                <p className="mt-3 text-center text-sm text-firefly/70 dark:text-sky-blue/70">
                    OpenAI starts the flow, but II-Agent still uses the normal
                    account login to create your app session.
                </p>
                {devAuthBypassEnabled ? (
                    <p className="mt-3 text-center text-sm text-firefly/70 dark:text-sky-blue/70">
                        Local dev auth bypass is active. Continue with II will
                        create a local app session on this machine when the
                        internal II IdP is unavailable.
                    </p>
                ) : null}
                {!openAIConnection?.readyToContinue ? (
                    iiContinueAvailable ? (
                        <Button
                            size="xl"
                            onClick={loginWithII}
                            className="w-full mt-4 bg-white text-black font-semibold shadow-btn"
                        >
                            <img
                                src="/images/logo-charcoal.png"
                                alt="logo"
                                className="size-[22px]"
                            />
                            {t('auth.continueWithII')}
                        </Button>
                    ) : iiOAuthAvailable === false ? (
                        <div className="mt-4 space-y-3">
                            <Button
                                size="xl"
                                disabled
                                className="w-full bg-white/70 text-black/60 font-semibold shadow-btn cursor-not-allowed"
                            >
                                <img
                                    src="/images/logo-charcoal.png"
                                    alt="logo"
                                    className="size-[22px] opacity-60"
                                />
                                {t('auth.continueWithII')}
                            </Button>
                            <p className="text-center text-sm text-firefly/70 dark:text-sky-blue/70">
                                II sign-in is unavailable in this environment
                                because `II_CLIENT_ID` is not configured on the
                                backend.
                            </p>
                        </div>
                    ) : null
                ) : null}
                {openAIConnection?.readyToContinue &&
                iiOAuthAvailable === false &&
                !devAuthBypassEnabled ? (
                    <p className="mt-4 text-center text-sm text-firefly/70 dark:text-sky-blue/70">
                        OpenAI is staged, but this local environment cannot
                        finish the handoff until `II_CLIENT_ID` is configured.
                    </p>
                ) : null}
                {googleOAuthEnabled ? (
                    <GoogleAuthButton
                        className="w-full mt-4 md:mt-6 bg-white text-black font-semibold shadow-btn"
                        label={t('auth.continueWithGoogle')}
                        onAuthCode={handleGoogleAuthCode}
                    />
                ) : (
                    <p className="mt-4 text-center text-sm text-firefly/70 dark:text-sky-blue/70">
                        Google sign-in is unavailable in this local environment
                        because `VITE_GOOGLE_CLIENT_ID` is not configured.
                    </p>
                )}
                <p className="text-xs text-center text-firefly/70 dark:text-sky-blue/70 mt-6">
                    {t('auth.privacyNotice')}{' '}
                    <br></br>
                    <a
                        href="/privacy"
                        className="underline hover:text-firefly dark:hover:text-sky-blue"
                    >
                        {t('auth.privacyNoticeLink')}
                    </a>
                </p>
            </div>
        </div>
    )
}

export const Component = LoginPage
