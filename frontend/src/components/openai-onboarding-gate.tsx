import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { settingsService } from '@/services/settings.service'
import type { IMcpSettings } from '@/typings/settings'

interface DeviceAuthState {
    loginId: string
    verificationUrl: string
    userCode: string
    intervalSeconds: number
}

interface OpenAIOnboardingGateProps {
    onConnected: (setting: IMcpSettings) => void
}

export function OpenAIOnboardingGate({
    onConnected
}: OpenAIOnboardingGateProps) {
    const [deviceAuth, setDeviceAuth] = useState<DeviceAuthState | null>(null)
    const [isConnectingOpenAI, setIsConnectingOpenAI] = useState(false)

    const verificationUrl = useMemo(
        () => deviceAuth?.verificationUrl || 'https://chatgpt.com/auth/device',
        [deviceAuth]
    )

    const handleConnectOpenAI = async () => {
        try {
            setIsConnectingOpenAI(true)
            const response = await settingsService.startCodexOpenAIDeviceOAuth({
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
            window.open(response.verification_url, '_blank', 'noopener,noreferrer')
        } catch (error: unknown) {
            console.error('Error starting OpenAI device auth:', error)
            const apiError = error as {
                response?: { data?: { detail?: string } }
            }
            toast.error(
                apiError.response?.data?.detail ||
                    'Failed to start OpenAI connection'
            )
        } finally {
            setIsConnectingOpenAI(false)
        }
    }

    useEffect(() => {
        if (!deviceAuth) {
            return
        }

        let isCancelled = false
        const poll = async () => {
            try {
                const response =
                    await settingsService.pollCodexOpenAIDeviceOAuth({
                        login_id: deviceAuth.loginId
                    })

                if (isCancelled || response.status === 'pending') {
                    return
                }

                if (response.status === 'completed' && response.setting) {
                    toast.success('OpenAI connected successfully')
                    onConnected(response.setting)
                    return
                }

                toast.error(
                    response.error || 'OpenAI connection failed. Start again.'
                )
                setDeviceAuth(null)
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
                        'OpenAI connection failed. Start again.'
                )
                setDeviceAuth(null)
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
    }, [deviceAuth, onConnected])

    return (
        <div className="min-h-screen bg-background px-4 py-8 md:px-8">
            <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-3xl items-center justify-center">
                <div className="w-full rounded-[32px] border border-black/10 bg-white p-8 shadow-[0_24px_60px_rgba(15,43,51,0.08)] dark:border-white/10 dark:bg-charcoal">
                    <div className="max-w-2xl space-y-6">
                        <div className="space-y-3">
                            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-blue">
                                OpenAI setup
                            </p>
                            <h1 className="text-3xl font-semibold text-firefly dark:text-white md:text-4xl">
                                Connect OpenAI before you start your first Codex task
                            </h1>
                            <p className="text-base leading-7 text-firefly/80 dark:text-white/72">
                                II-Agent can already use your OpenAI-backed Codex
                                access. The current UX hides it in tool settings,
                                so this page puts the required connection first.
                            </p>
                        </div>

                        <div className="grid gap-3 rounded-3xl bg-firefly/5 p-5 dark:bg-sky-blue-2/5 md:grid-cols-3">
                            <div className="rounded-2xl bg-white/90 p-4 dark:bg-white/5">
                                <p className="text-sm font-semibold text-firefly dark:text-white">
                                    1. Start sign-in
                                </p>
                                <p className="mt-2 text-sm text-firefly/70 dark:text-white/65">
                                    Launch the OpenAI device flow from this page.
                                </p>
                            </div>
                            <div className="rounded-2xl bg-white/90 p-4 dark:bg-white/5">
                                <p className="text-sm font-semibold text-firefly dark:text-white">
                                    2. Verify in browser
                                </p>
                                <p className="mt-2 text-sm text-firefly/70 dark:text-white/65">
                                    Enter the one-time code in the OpenAI window.
                                </p>
                            </div>
                            <div className="rounded-2xl bg-white/90 p-4 dark:bg-white/5">
                                <p className="text-sm font-semibold text-firefly dark:text-white">
                                    3. Return here
                                </p>
                                <p className="mt-2 text-sm text-firefly/70 dark:text-white/65">
                                    We poll for completion and unlock the app
                                    automatically.
                                </p>
                            </div>
                        </div>

                        {deviceAuth ? (
                            <div className="space-y-4 rounded-3xl border border-sky-blue/30 bg-sky-blue/10 p-5 dark:border-sky-blue-2/30 dark:bg-sky-blue-2/10">
                                <div>
                                    <p className="text-sm font-semibold text-firefly dark:text-white">
                                        Finish sign-in in your browser
                                    </p>
                                    <p className="mt-1 text-sm text-firefly/75 dark:text-white/70">
                                        Open the verification page and enter this
                                        one-time code.
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
                                        className="flex-1 bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black"
                                        onClick={() =>
                                            window.open(
                                                verificationUrl,
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
                        ) : (
                            <div className="flex flex-col gap-3 md:flex-row">
                                <Button
                                    type="button"
                                    size="xl"
                                    className="bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black"
                                    disabled={isConnectingOpenAI}
                                    onClick={handleConnectOpenAI}
                                >
                                    {isConnectingOpenAI
                                        ? 'Starting OpenAI sign-in...'
                                        : 'Connect OpenAI'}
                                </Button>
                                <Button
                                    type="button"
                                    size="xl"
                                    variant="outline"
                                    asChild
                                >
                                    <Link to="/settings/general">
                                        Open Advanced Codex Settings
                                    </Link>
                                </Button>
                            </div>
                        )}

                        <p className="text-sm text-firefly/65 dark:text-white/60">
                            Need the manual route instead? Open Codex settings to
                            paste `auth.json` or an API key.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    )
}
