import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import dayjs from 'dayjs'

import { settingsService } from '@/services/settings.service'
import { useAppSelector } from '@/state'
import { ISetting } from '@/typings'
import { toast } from 'sonner'

import { Button } from '../ui/button'
import { Icon } from '../ui/icon'
import { Sheet, SheetClose, SheetContent, SheetHeader } from '../ui/sheet'

interface ClaudeCodeSettingProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    onSaveConfig: (data: ISetting) => void
}

interface ClaudeCodeAuthMessage {
    type?: string
    code?: string
    state?: string
    error?: string
    errorDescription?: string
}

const ClaudeCodeSetting = ({
    open,
    onOpenChange,
    onSaveConfig
}: ClaudeCodeSettingProps) => {
    const isSavingSetting = useAppSelector(
        (state) => state.settings.isSavingSetting
    )
    const currentSettingData = useAppSelector(
        (state) => state.settings.currentSettingData
    )
    const claudeCodeConfig = useAppSelector(
        (state) => state.settings.claudeCodeConfig
    )

    const [oauthLoginId, setOauthLoginId] = useState<string | null>(null)
    const [isConnectingClaude, setIsConnectingClaude] = useState(false)
    const popupRef = useRef<Window | null>(null)

    const callbackUrl = useMemo(
        () => `${window.location.origin}/claude-code-callback`,
        []
    )

    const handleCancel = useCallback(() => {
        popupRef.current?.close()
        popupRef.current = null
        setOauthLoginId(null)
        setIsConnectingClaude(false)
        onOpenChange(false)
    }, [onOpenChange])

    const completeClaudeSave = useCallback(() => {
        toast.success(
            'Claude Code configuration saved and activated successfully'
        )
        popupRef.current?.close()
        popupRef.current = null
        setOauthLoginId(null)
        setIsConnectingClaude(false)
        onOpenChange(false)
        onSaveConfig(currentSettingData as ISetting)
    }, [currentSettingData, onOpenChange, onSaveConfig])

    const handleLoginWithClaude = useCallback(async () => {
        try {
            setIsConnectingClaude(true)

            const response = await settingsService.startClaudeCodeOAuth({
                redirect_uri: callbackUrl
            })

            setOauthLoginId(response.login_id)

            const width = 540
            const height = 760
            const left = window.screenX + (window.outerWidth - width) / 2
            const top = window.screenY + (window.outerHeight - height) / 2
            const features = [
                `width=${Math.max(420, Math.floor(width))}`,
                `height=${Math.max(560, Math.floor(height))}`,
                `left=${Math.max(0, Math.floor(left))}`,
                `top=${Math.max(0, Math.floor(top))}`,
                'resizable=yes',
                'scrollbars=yes'
            ].join(',')

            const popup = window.open(
                response.authorization_url,
                'claude-code-oauth',
                features
            )

            if (!popup) {
                setIsConnectingClaude(false)
                setOauthLoginId(null)
                toast.error(
                    'Claude Code login requires a popup window. Allow popups and try again.'
                )
                return
            }

            popupRef.current = popup
            popup.focus()
            setIsConnectingClaude(false)
        } catch (error: unknown) {
            console.error('Error starting Claude Code OAuth:', error)
            const apiError = error as {
                response?: { data?: { detail?: string } }
            }
            toast.error(
                apiError.response?.data?.detail ||
                    'Failed to start Claude Code connection'
            )
            setOauthLoginId(null)
            setIsConnectingClaude(false)
        }
    }, [callbackUrl])

    useEffect(() => {
        if (!open) {
            popupRef.current?.close()
            popupRef.current = null
            setOauthLoginId(null)
            setIsConnectingClaude(false)
        }
    }, [open])

    useEffect(() => {
        if (!open) {
            return
        }

        const handleMessage = async (event: MessageEvent<ClaudeCodeAuthMessage>) => {
            if (event.origin !== window.location.origin) {
                return
            }

            const payload = event.data
            if (!payload || payload.type !== 'claude-code-auth') {
                return
            }

            if (payload.error) {
                popupRef.current?.close()
                popupRef.current = null
                setOauthLoginId(null)
                setIsConnectingClaude(false)
                toast.error(
                    payload.errorDescription ||
                        'Claude Code authorization was cancelled.'
                )
                return
            }

            if (!payload.code || !payload.state || !oauthLoginId) {
                popupRef.current?.close()
                popupRef.current = null
                setOauthLoginId(null)
                setIsConnectingClaude(false)
                toast.error(
                    'Claude Code authorization response was incomplete. Start again.'
                )
                return
            }

            try {
                await settingsService.completeClaudeCodeOAuth({
                    login_id: oauthLoginId,
                    code: payload.code,
                    state: payload.state
                })
                completeClaudeSave()
            } catch (error: unknown) {
                console.error('Error completing Claude Code OAuth:', error)
                const apiError = error as {
                    response?: { data?: { detail?: string } }
                }
                popupRef.current?.close()
                popupRef.current = null
                setOauthLoginId(null)
                setIsConnectingClaude(false)
                toast.error(
                    apiError.response?.data?.detail ||
                        'Failed to complete Claude Code connection'
                )
            }
        }

        window.addEventListener('message', handleMessage)
        return () => window.removeEventListener('message', handleMessage)
    }, [completeClaudeSave, oauthLoginId, open])

    const connectionCopy = oauthLoginId
        ? 'Complete the Anthropic approval in the popup. We will finish the connection automatically.'
        : 'Connect Claude Code with Anthropic OAuth. No manual code copy/paste is required.'

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                className="px-3 md:px-6 pt-3 md:pt-12 w-full !max-w-[560px]"
                accessibleTitle="Claude Code"
            >
                <SheetHeader className="p-0 gap-6 pb-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-x-2">
                            <Icon name="claude" className="size-9 md:size-12" />
                            <div className="space-y-1">
                                <p className="text-xl md:text-2xl font-semibold dark:text-white">
                                    Claude Code
                                </p>
                                <p className="text-sm md:text-base dark:text-white/[0.56]">
                                    Anthropic
                                </p>
                            </div>
                        </div>
                        <div className="flex items-center gap-x-4">
                            <SheetClose className="cursor-pointer">
                                <Icon
                                    name="arrow-right"
                                    className="dark:inline hidden"
                                />
                                <Icon
                                    name="arrow-right-dark"
                                    className="dark:hidden inline"
                                />
                            </SheetClose>
                        </div>
                    </div>
                </SheetHeader>
                <div className="overflow-auto pb-4 md:pb-12">
                    <p className="dark:text-white text-lg font-semibold">
                        About
                    </p>
                    <p className="dark:text-white text-sm mt-3">
                        Enable Claude Code for autonomous code generation and
                        review.
                    </p>
                    <Button
                        className="h-[22px] bg-firefly dark:bg-sky-blue-2 text-sky-blue-2 dark:text-black gap-x-[6px] mt-4 text-xs rounded-full !font-normal"
                        onClick={() =>
                            window.open(
                                'https://www.anthropic.com/claude/code',
                                '_blank'
                            )
                        }
                    >
                        <Icon
                            name="global"
                            className="size-4 fill-sky-blue-2 dark:fill-black"
                        />
                        Remote
                    </Button>

                    <p className="dark:text-white text-lg font-semibold mt-6">
                        Credentials
                    </p>

                    <div className="mt-3 rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                        <p className="text-sm dark:text-white/80">
                            {connectionCopy}
                        </p>
                        <Button
                            type="button"
                            className="h-10 rounded-xl text-sm bg-[#191918] dark:bg-white text-white dark:text-black border-0 gap-x-2"
                            onClick={() => void handleLoginWithClaude()}
                            disabled={isConnectingClaude || isSavingSetting}
                        >
                            <Icon name="claude" className="size-5" />
                            {oauthLoginId
                                ? 'Restart Claude login'
                                : 'Connect with Claude'}
                        </Button>
                    </div>

                    {claudeCodeConfig?.updated_at && (
                        <div className="mt-4 flex gap-x-2 items-center text-sm italic">
                            <span className="font-semibold">
                                Latest update:
                            </span>
                            <span>
                                {dayjs(claudeCodeConfig.updated_at).format(
                                    'DD/MM/YYYY -- hh:mmA'
                                )}
                            </span>
                        </div>
                    )}
                    <div className="space-y-4 grid grid-cols-2 gap-4 mt-6">
                        <Button
                            type="button"
                            variant="outline"
                            className="h-12 rounded-xl text-base"
                            onClick={handleCancel}
                        >
                            Cancel
                        </Button>
                        <Button
                            className="h-12 rounded-xl bg-sky-blue text-black text-base"
                            onClick={() =>
                                window.open(
                                    'https://www.anthropic.com/claude/code',
                                    '_blank'
                                )
                            }
                        >
                            Learn More
                        </Button>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    )
}

export default ClaudeCodeSetting
