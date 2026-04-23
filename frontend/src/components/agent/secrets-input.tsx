'use client'

import { useState } from 'react'
import {
    Eye,
    EyeOff,
    Lock,
    Key,
    Loader2,
    X
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { useTranslation } from 'react-i18next'

export interface Secret {
    key: string
    value: string
    description?: string
}

interface SecretsInputProps {
    secrets: Secret[]
    message?: string
    /**
     * When true, displays secrets in read-only mode without input fields or action buttons.
     * Useful for showing previously saved secrets or displaying secrets after submission.
     */
    readOnly?: boolean
    /**
     * When true, keeps the form visible but disables interaction.
     * Useful for stale or already-submitted ask_user prompts in history.
     */
    disabled?: boolean
    /**
     * Session ID for continuing the paused run after the user supplies secrets.
     * Required for interactive mode.
     */
    sessionId?: string
    /**
     * Callback when user confirms the provided secret values.
     * Required for interactive mode.
     */
    onConfirm?: (
        confirmed: boolean,
        userInput?: Record<string, string>
    ) => void
    /**
     * Callback when user cancels.
     */
    onCancel?: () => void
}

export const SecretsInput = ({
    secrets,
    message,
    readOnly = false,
    disabled = false,
    sessionId,
    onConfirm,
    onCancel
}: SecretsInputProps) => {
    const { t } = useTranslation()

    const [isSubmitting, setIsSubmitting] = useState(false)
    const [secretValues, setSecretValues] = useState<Record<string, string>>(
        () => {
            const initial: Record<string, string> = {}
            secrets.forEach((secret) => {
                initial[secret.key] = secret.value || ''
            })
            return initial
        }
    )
    const [showValues, setShowValues] = useState(false)

    const handleValueChange = (key: string, value: string) => {
        setSecretValues((prev) => ({
            ...prev,
            [key]: value
        }))
    }

    const handleSecretsSubmit = async () => {
        if (!sessionId || !onConfirm) return

        const secretsObject: Record<string, string> = {}
        secrets.forEach((secret) => {
            const value = secretValues[secret.key]
            if (secret.key && value) {
                secretsObject[secret.key] = value
            }
        })

        if (Object.keys(secretsObject).length === 0) {
            toast.error(t('agent.secrets.errors.atLeastOneValue'))
            return
        }

        setIsSubmitting(true)
        onConfirm(true, secretsObject)
    }

    // Determine if we're in interactive mode
    const isInteractive = !readOnly && !disabled && sessionId && onConfirm
    const inputsDisabled = isSubmitting || disabled

    return (
        <div className="mt-3 space-y-3 bg-firefly/[0.18] dark:bg-sky-blue/[0.18] border border-grey rounded-xl p-4">
            <div className="flex items-center gap-2">
                <Lock className="size-4" />
                <span className="text-sm font-medium">
                    {t('agent.secrets.environmentVariables')}
                </span>
            </div>

            {disabled && !readOnly && (
                <p className="text-xs text-gray-500 dark:text-gray-400">
                    {t('agent.toolConfirmation.inactive')}
                </p>
            )}

            {message && <p className="text-xs text-gray-400">{message}</p>}

            <div className="space-y-3">
                {secrets.map((secret) => (
                    <div key={secret.key} className="space-y-1.5">
                        <div className="flex items-center gap-2">
                            <Key className="size-3 text-gray-400" />
                            <span className="text-sm font-medium">
                                {secret.key}
                            </span>
                        </div>
                        {secret.description && (
                            <p className="text-xs text-gray-400 pl-5">
                                {secret.description}
                            </p>
                        )}
                        {readOnly ? (
                            <div className="flex items-center gap-2 pl-5">
                                <span className="text-xs text-gray-500">
                                    {showValues
                                        ? secret.value || '(empty)'
                                        : secret.value
                                          ? '••••••••'
                                          : '(empty)'}
                                </span>
                                {secret.value && (
                                    <button
                                        onClick={() =>
                                            setShowValues(!showValues)
                                        }
                                        className="cursor-pointer p-0.5 hover:bg-white/10 rounded transition-colors"
                                    >
                                        {showValues ? (
                                            <EyeOff className="size-3 text-gray-400" />
                                        ) : (
                                            <Eye className="size-3 text-gray-400" />
                                        )}
                                    </button>
                                )}
                            </div>
                        ) : (
                            <div className="relative">
                                <Input
                                    type={showValues ? 'text' : 'password'}
                                    value={secretValues[secret.key] || ''}
                                    onChange={(e) =>
                                        handleValueChange(
                                            secret.key,
                                            e.target.value
                                        )
                                    }
                                    className="h-9 text-sm bg-white dark:bg-[#A6FFFF1A] border-grey rounded-lg pr-10"
                                    placeholder={t('agent.secrets.placeholder', {
                                        key: secret.key
                                    })}
                                    disabled={inputsDisabled}
                                />
                                <button
                                    onClick={() => setShowValues(!showValues)}
                                    className="cursor-pointer absolute top-[10px] right-2 p-0.5 hover:bg-white/10 rounded transition-colors"
                                    disabled={inputsDisabled}
                                >
                                    {showValues ? (
                                        <EyeOff className="size-3" />
                                    ) : (
                                        <Eye className="size-3" />
                                    )}
                                </button>
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {isInteractive && (
                <div className="flex gap-2 pt-1">
                    <Button
                        onClick={handleSecretsSubmit}
                        disabled={isSubmitting}
                        className="text-xs font-semibold bg-firefly text-sky-blue dark:bg-sky-blue dark:text-black hover:opacity-90"
                    >
                        {isSubmitting ? (
                            <>
                                <Loader2 className="size-3 mr-1 animate-spin" />
                                {t('common.saving')}
                            </>
                        ) : (
                            t('common.continue')
                        )}
                    </Button>
                    {onCancel && (
                        <Button
                            onClick={onCancel}
                            disabled={isSubmitting}
                            variant="outline"
                            className="text-xs font-semibold border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                        >
                            <X className="size-3 mr-1" />
                            {t('common.cancel')}
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}
