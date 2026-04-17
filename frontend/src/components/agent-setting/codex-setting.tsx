import { useEffect, useMemo, useState } from 'react'

import { settingsService } from '@/services/settings.service'
import { useAppSelector } from '@/state'
import { ISetting } from '@/typings'
import { IMcpSettings } from '@/typings/settings'
import { toast } from 'sonner'
import { hasCodexAuth } from '@/lib/codex'

import { Button } from '../ui/button'
import { Icon } from '../ui/icon'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from '../ui/select'
import { Sheet, SheetClose, SheetContent, SheetHeader } from '../ui/sheet'
import { Switch } from '../ui/switch'
import { Textarea } from '../ui/textarea'

interface CodexSettingProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    onSaveConfig: (data: ISetting) => void
}

interface DeviceAuthState {
    loginId: string
    verificationUrl: string
    userCode: string
    intervalSeconds: number
}

const CodexSetting = ({
    open,
    onOpenChange,
    onSaveConfig
}: CodexSettingProps) => {
    const isSavingSetting = useAppSelector(
        (state) => state.settings.isSavingSetting
    )
    const currentSettingData = useAppSelector(
        (state) => state.settings.currentSettingData
    )

    const [authJson, setAuthJson] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [model, setModel] = useState('gpt-5')
    const [reasoningEffort, setReasoningEffort] = useState('medium')
    const [searchEnabled, setSearchEnabled] = useState(false)
    const [existingCodexSetting, setExistingCodexSetting] =
        useState<IMcpSettings | null>(null)
    const [deviceAuth, setDeviceAuth] = useState<DeviceAuthState | null>(null)
    const [isConnectingOpenAI, setIsConnectingOpenAI] = useState(false)

    const hasExistingAuth = useMemo(
        () => hasCodexAuth(existingCodexSetting),
        [existingCodexSetting]
    )

    const handleCancel = () => {
        setDeviceAuth(null)
        onOpenChange(false)
    }

    const completeCodexSave = (setting?: IMcpSettings) => {
        if (setting) {
            setExistingCodexSetting(setting)
        }
        toast.success('Codex configuration saved and activated successfully')
        setDeviceAuth(null)
        setAuthJson('')
        setApiKey('')
        onOpenChange(false)
        onSaveConfig(currentSettingData as ISetting)
    }

    const handleSaveConfig = async () => {
        const payload: {
            auth_json?: Record<string, unknown>
            model?: string
            apikey?: string
            model_reasoning_effort?: string
            search?: boolean
        } = {
            model: model.trim() || undefined,
            model_reasoning_effort: reasoningEffort,
            search: searchEnabled
        }

        if (authJson.trim()) {
            try {
                payload.auth_json = JSON.parse(authJson)
            } catch {
                toast.warning('Invalid JSON format for auth configuration')
                return
            }
        }

        if (apiKey.trim()) {
            payload.apikey = apiKey.trim()
        }

        if (!payload.auth_json && !payload.apikey && !hasExistingAuth) {
            toast.warning(
                'Connect OpenAI or provide Auth JSON / API Key before saving'
            )
            return
        }

        try {
            const setting = await settingsService.configureCodex(payload)
            completeCodexSave(setting)
        } catch (error: unknown) {
            console.error('Error saving Codex configuration:', error)
            const apiError = error as {
                response?: { data?: { detail?: string } }
            }
            toast.error(
                apiError.response?.data?.detail ||
                    'Failed to save Codex configuration'
            )
        }
    }

    const handleConnectOpenAI = async () => {
        try {
            setIsConnectingOpenAI(true)
            const response = await settingsService.startCodexOpenAIDeviceOAuth({
                model: model.trim() || undefined,
                model_reasoning_effort: reasoningEffort,
                search: searchEnabled
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
        const loadCodexSettings = async () => {
            if (!open) {
                return
            }

            try {
                const codexSetting = await settingsService.getCodexSettings()
                setExistingCodexSetting(codexSetting)
                setAuthJson('')
                setApiKey('')
                setDeviceAuth(null)

                if (codexSetting?.metadata) {
                    setModel(codexSetting.metadata.model || 'gpt-5')
                    setReasoningEffort(
                        codexSetting.metadata.model_reasoning_effort || 'medium'
                    )
                    setSearchEnabled(Boolean(codexSetting.metadata.search))
                } else {
                    setModel('gpt-5')
                    setReasoningEffort('medium')
                    setSearchEnabled(false)
                }
            } catch (error) {
                console.error('Error loading Codex settings:', error)
            }
        }

        loadCodexSettings()
    }, [open])

    useEffect(() => {
        if (!open || !deviceAuth) {
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
                    completeCodexSave(response.setting)
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
    }, [deviceAuth, open])

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                className="px-3 md:px-6 pt-3 md:pt-12 w-full !max-w-[560px]"
                accessibleTitle="Codex"
            >
                <SheetHeader className="p-0 gap-6 pb-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-x-2">
                            <Icon name="codex" className="size-12" />
                            <div className="md:space-y-1">
                                <p className="text-xl md:text-2xl font-semibold dark:text-white">
                                    Codex
                                </p>
                                <p className="text-sm md:text-base dark:text-white/[0.56]">
                                    OpenAI
                                </p>
                            </div>
                        </div>
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
                </SheetHeader>
                <div className="overflow-auto pb-4 md:pb-12">
                    <p className="dark:text-white text-lg font-semibold">
                        About
                    </p>
                    <p className="dark:text-white text-sm mt-3">
                        Enable OpenAI Codex for autonomous code generation and
                        review.
                    </p>
                    <Button
                        className="h-[22px] bg-firefly dark:bg-sky-blue-2 text-sky-blue-2 dark:text-black gap-x-[6px] mt-4 text-xs rounded-full !font-normal"
                        onClick={() =>
                            window.open('https://openai.com/codex/', '_blank')
                        }
                    >
                        <Icon
                            name="global"
                            className="size-4 fill-sky-blue-2 dark:fill-black"
                        />
                        Remote
                    </Button>

                    <div className="mt-6 space-y-4">
                        <div className="space-y-2">
                            <Label
                                htmlFor="codex-model"
                                className="dark:text-white text-sm"
                            >
                                Model
                            </Label>
                            <Select value={model} onValueChange={setModel}>
                                <SelectTrigger
                                    id="codex-model"
                                    className="w-full"
                                >
                                    <SelectValue placeholder="Select model" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="gpt-5">gpt-5</SelectItem>
                                    <SelectItem value="gpt-5.2">
                                        gpt-5.2
                                    </SelectItem>
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="flex items-center justify-between p-4 rounded-2xl bg-firefly/10 dark:bg-sky-blue-2/5">
                            <div className="flex-1">
                                <p className="text-base font-semibold dark:text-white">
                                    Enable Search
                                </p>
                                <p className="mt-1 dark:text-white/[0.56] text-sm">
                                    Allow Codex to search for additional context
                                </p>
                            </div>
                            <Switch
                                checked={searchEnabled}
                                onCheckedChange={setSearchEnabled}
                            />
                        </div>
                    </div>

                    <div className="mt-6 rounded-2xl border border-black/10 dark:border-white/10 p-4 space-y-3">
                        <div className="flex items-start justify-between gap-3">
                            <div>
                                <p className="text-base font-semibold dark:text-white">
                                    OpenAI OAuth
                                </p>
                                <p className="mt-1 text-sm dark:text-white/[0.56]">
                                    Connect your ChatGPT-backed Codex access
                                    without pasting tokens into the browser.
                                </p>
                            </div>
                            {existingCodexSetting?.metadata?.auth_mode ===
                                'openai_oauth' && hasExistingAuth && (
                                <span className="text-xs rounded-full px-2 py-1 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                                    Connected
                                </span>
                            )}
                        </div>

                        {existingCodexSetting?.metadata?.auth_mode ===
                            'openai_oauth' &&
                            hasExistingAuth && (
                                <div className="text-sm dark:text-white/[0.72] space-y-1">
                                    {existingCodexSetting.metadata
                                        ?.chatgpt_plan_type && (
                                        <p>
                                            Plan:{' '}
                                            {
                                                existingCodexSetting.metadata
                                                    .chatgpt_plan_type
                                            }
                                        </p>
                                    )}
                                    {existingCodexSetting.metadata
                                        ?.chatgpt_account_id && (
                                        <p>
                                            Workspace:{' '}
                                            {
                                                existingCodexSetting.metadata
                                                    .chatgpt_account_id
                                            }
                                        </p>
                                    )}
                                </div>
                            )}

                        {deviceAuth ? (
                            <div className="space-y-3 rounded-xl bg-firefly/10 dark:bg-sky-blue-2/5 p-4">
                                <p className="text-sm font-medium dark:text-white">
                                    Finish sign-in in your browser
                                </p>
                                <p className="text-sm dark:text-white/[0.72]">
                                    Open the verification page and enter this
                                    one-time code.
                                </p>
                                <div className="rounded-xl bg-black/5 dark:bg-white/5 px-4 py-3">
                                    <p className="text-xs uppercase tracking-wide dark:text-white/[0.56]">
                                        Code
                                    </p>
                                    <p className="text-lg font-semibold dark:text-white">
                                        {deviceAuth.userCode}
                                    </p>
                                </div>
                                <div className="flex gap-3">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        className="flex-1"
                                        onClick={() =>
                                            window.open(
                                                deviceAuth.verificationUrl,
                                                '_blank'
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
                            <Button
                                type="button"
                                className="w-full h-12 rounded-xl bg-sky-blue text-black text-base"
                                disabled={isConnectingOpenAI}
                                onClick={handleConnectOpenAI}
                            >
                                {isConnectingOpenAI
                                    ? 'Starting OpenAI sign-in...'
                                    : 'Connect OpenAI'}
                            </Button>
                        )}
                    </div>

                    <p className="dark:text-white text-lg font-semibold mt-6">
                        Manual Fallback
                    </p>
                    <p className="text-sm mt-3 dark:text-white/[0.72]">
                        Use this only if you want to paste Codex auth JSON or an
                        API key directly.
                    </p>

                    <div className="space-y-2 relative mt-3">
                        <Icon
                            name="key-square"
                            className={`absolute top-3 left-4 fill-black dark:fill-white ${authJson ? '' : 'opacity-30'}`}
                        />
                        <Textarea
                            id="auth-json"
                            className="pl-[56px] min-h-[144px] mb-4"
                            placeholder="Enter Codex auth.json contents"
                            value={authJson}
                            onChange={(e) => setAuthJson(e.target.value)}
                        />
                    </div>

                    <div className="mt-6 space-y-4">
                        <div className="space-y-2">
                            <Label
                                htmlFor="codex-apikey"
                                className="dark:text-white text-sm"
                            >
                                API Key
                            </Label>
                            <Input
                                id="codex-apikey"
                                type="password"
                                placeholder="Enter API Key"
                                value={apiKey}
                                onChange={(e) => setApiKey(e.target.value)}
                            />
                        </div>
                    </div>

                    {hasExistingAuth && !authJson.trim() && !apiKey.trim() && (
                        <p className="mt-4 text-sm dark:text-white/[0.56]">
                            Saving without new credentials will keep the
                            existing Codex auth and only update model/search
                            options.
                        </p>
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
                            disabled={isSavingSetting || isConnectingOpenAI}
                            onClick={handleSaveConfig}
                        >
                            {isSavingSetting ? 'Saving...' : 'Save'}
                        </Button>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    )
}

export default CodexSetting
