'use client'

import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../ui/button'
import { ToolConfirmationData, TOOL, CommandType } from '@/typings/agent'
import { useSocketIOContext } from '@/contexts/websocket-context'
import { selectIsWaitingForInput, useAppDispatch, useAppSelector } from '@/state'
import { setRunStatus } from '@/state/slice/agent'
import { setLoading } from '@/state/slice/ui'
import { SecretsInput } from './secrets-input'

interface ToolConfirmationProps {
    confirmation: ToolConfirmationData
}

export function ToolConfirmation({ confirmation }: ToolConfirmationProps) {
    const { t } = useTranslation()
    const { sendMessage } = useSocketIOContext()
    const dispatch = useAppDispatch()
    const isWaitingForInput = useAppSelector(selectIsWaitingForInput)
    const [isResponding, setIsResponding] = useState(false)
    const isInteractive = isWaitingForInput && !confirmation.resolved

    // Get tool info from the first active requirement
    const requirement = confirmation.active_requirements[0]
    const toolName =
        requirement?.tool_execution?.tool_name ||
        t('agent.toolConfirmation.unknownTool')
    const toolArgs = requirement?.tool_execution?.tool_args || {}
    const userInputSchema = requirement?.user_input_schema || []
    const requiresUserInput = Boolean(requirement?.needs_user_input)
    const isCodexApproval = toolName.startsWith('codex_')

    const handleContinue = (payload: {
        confirmed?: boolean
        decision?: 'approve_once' | 'approve_session' | 'reject' | 'cancel'
        userInput?: Record<string, string>
    }) => {
        if (isResponding || !isInteractive) return

        setIsResponding(true)
        dispatch(setRunStatus('running'))
        dispatch(setLoading(true))

        // Send continue_run command to backend
        sendMessage({
            session_uuid: confirmation.session_id,
            content: {
                command: CommandType.CONTINUE_RUN,
                run_id: confirmation.run_id,
                ...(payload.decision
                    ? { decision: payload.decision }
                    : { confirmed: Boolean(payload.confirmed) }),
                ...(payload.userInput ? { user_input: payload.userInput } : {})
            }
        })
    }

    const handleConfirm = (
        confirmed: boolean,
        userInput?: Record<string, string>
    ) => {
        handleContinue({ confirmed, userInput })
    }

    const handleDecision = (
        decision: 'approve_once' | 'approve_session' | 'reject' | 'cancel',
        userInput?: Record<string, string>
    ) => {
        handleContinue({ decision, userInput })
    }

    // Show processing state when responding
    if (isResponding) {
        return (
            <div className="mt-3 flex items-center gap-2 text-sm text-gray-500">
                <div className="animate-pulse">
                    {t('agent.toolConfirmation.processingResponse')}
                </div>
            </div>
        )
    }

    if (requiresUserInput && userInputSchema.length > 0) {
        return (
            <GenericUserInputUI
                fields={userInputSchema}
                toolArgs={toolArgs}
                disabled={!isInteractive}
                onSubmit={(values) => handleConfirm(true, values)}
                onCancel={() => handleConfirm(false)}
            />
        )
    }

    // Render tool-specific confirmation UI based on tool type
    switch (toolName) {
        case TOOL.ASK_USER_ENV: {
            const requestedKeys =
                (
                    toolArgs as {
                        requested_keys?: Array<{
                            key: string
                            description?: string
                        }>
                    }
                )?.requested_keys || []
            const message = (toolArgs as { message?: string })?.message

            return (
                <SecretsInput
                    secrets={requestedKeys.map((item) => ({
                        key: item.key,
                        value: '',
                        description: item.description
                    }))}
                    message={message}
                    disabled={!isInteractive}
                    sessionId={confirmation.session_id}
                    onConfirm={handleConfirm}
                    onCancel={() => handleConfirm(false)}
                />
            )
        }

        case TOOL.ASK_USER_SELECT: {
            return (
                <AskUserSelectUI
                    toolArgs={toolArgs}
                    disabled={!isInteractive}
                    onSelect={(selected) =>
                        handleConfirm(true, { selected })
                    }
                    onSkip={() => handleConfirm(false)}
                />
            )
        }

        default:
            // Default confirmation UI for generic tools
            return (
                <div className="mt-3 border border-gray-300 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-[#1e1e1e]">
                    {!isInteractive && (
                        <div className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                            {t('agent.toolConfirmation.inactive')}
                        </div>
                    )}
                    <div className="mb-3">
                        <div className="text-sm font-medium text-gray-900 dark:text-gray-100 mb-1">
                            {t('agent.toolConfirmation.tool')}: {toolName}
                        </div>
                        {Object.keys(toolArgs).length > 0 && (
                            <div className="text-xs text-gray-600 dark:text-gray-400 mt-2">
                                <details className="cursor-pointer">
                                    <summary className="hover:text-gray-800 dark:hover:text-gray-200">
                                        {t(
                                            'agent.toolConfirmation.viewArguments'
                                        )}
                                    </summary>
                                    <pre className="mt-2 p-2 bg-gray-100 dark:bg-[#2d2d2d] rounded text-xs overflow-x-auto">
                                        {JSON.stringify(toolArgs, null, 2)}
                                    </pre>
                                </details>
                            </div>
                        )}
                    </div>

                    <div className="flex flex-wrap gap-3">
                        {isCodexApproval ? (
                            <>
                                <Button
                                    onClick={() =>
                                        handleDecision('approve_once')
                                    }
                                    className="flex-1 min-w-[140px] bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 flex items-center justify-center gap-2"
                                    disabled={isResponding || !isInteractive}
                                >
                                    <Check className="size-4" />
                                    Approve once
                                </Button>
                                <Button
                                    onClick={() =>
                                        handleDecision('approve_session')
                                    }
                                    className="flex-1 min-w-[160px] bg-emerald-700 hover:bg-emerald-800 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 flex items-center justify-center gap-2"
                                    disabled={isResponding || !isInteractive}
                                >
                                    <Check className="size-4" />
                                    Approve session
                                </Button>
                            </>
                        ) : (
                            <Button
                                onClick={() => handleConfirm(true)}
                                className="flex-1 bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 flex items-center justify-center gap-2"
                                disabled={isResponding || !isInteractive}
                            >
                                <Check className="size-4" />
                                {t('agent.toolConfirmation.yesContinue')}
                            </Button>
                        )}
                        <Button
                            onClick={() =>
                                isCodexApproval
                                    ? handleDecision('reject')
                                    : handleConfirm(false)
                            }
                            variant="outline"
                            className="flex-1 border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 font-medium py-2 px-4 rounded-lg transition-colors duration-200 flex items-center justify-center gap-2"
                            disabled={isResponding || !isInteractive}
                        >
                            <X className="size-4" />
                            {t('agent.toolConfirmation.noCancel')}
                        </Button>
                    </div>
                </div>
            )
    }
}

// --- Generic user input UI ---

interface GenericUserInputField {
    name: string
    field_type: string
    description?: string
    value?: unknown
}

interface GenericQuestionOption {
    label: string
    description?: string
}

interface GenericQuestion {
    id: string
    header?: string
    question?: string
    isOther?: boolean
    options?: GenericQuestionOption[]
}

interface GenericUserInputUIProps {
    fields: GenericUserInputField[]
    toolArgs: Record<string, unknown>
    disabled?: boolean
    onSubmit: (values: Record<string, string>) => void
    onCancel: () => void
}

function GenericUserInputUI({
    fields,
    toolArgs,
    disabled = false,
    onSubmit,
    onCancel
}: GenericUserInputUIProps) {
    const { t } = useTranslation()
    const questions = Array.isArray(toolArgs.questions)
        ? (toolArgs.questions as GenericQuestion[])
        : []
    const [values, setValues] = useState<Record<string, string>>(() =>
        Object.fromEntries(
            fields.map((field) => [
                field.name,
                typeof field.value === 'string' ? field.value : ''
            ])
        )
    )

    const allRequiredAnswered = fields.every((field) =>
        values[field.name]?.trim()
    )

    const updateValue = (name: string, value: string) => {
        setValues((current) => ({ ...current, [name]: value }))
    }

    return (
        <div className="mt-3 w-full max-w-2xl rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#1e1e1e] p-4 shadow-sm">
            {disabled && (
                <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                    {t('agent.toolConfirmation.inactive')}
                </p>
            )}

            <div className="space-y-4">
                {fields.map((field) => {
                    const question = questions.find((q) => q.id === field.name)
                    const label =
                        question?.question ||
                        field.description ||
                        question?.header ||
                        field.name
                    const options = question?.options || []

                    return (
                        <div key={field.name} className="space-y-2">
                            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                                {label}
                            </p>

                            {options.length > 0 ? (
                                <div className="flex flex-col gap-2">
                                    {options.map((option) => {
                                        const isSelected =
                                            values[field.name] === option.label
                                        return (
                                            <button
                                                key={option.label}
                                                type="button"
                                                onClick={() =>
                                                    updateValue(
                                                        field.name,
                                                        option.label
                                                    )
                                                }
                                                disabled={disabled}
                                                className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                                                    isSelected
                                                        ? 'border-sky-500 bg-sky-50 text-sky-950 dark:bg-sky-950/30 dark:text-sky-100'
                                                        : 'border-gray-200 bg-gray-50 text-gray-700 hover:bg-gray-100 dark:border-gray-700 dark:bg-[#2d2d2d] dark:text-gray-300'
                                                }`}
                                            >
                                                <span className="block font-medium">
                                                    {option.label}
                                                </span>
                                                {option.description && (
                                                    <span className="mt-0.5 block text-xs opacity-75">
                                                        {option.description}
                                                    </span>
                                                )}
                                            </button>
                                        )
                                    })}
                                </div>
                            ) : (
                                <input
                                    value={values[field.name] || ''}
                                    onChange={(event) =>
                                        updateValue(
                                            field.name,
                                            event.target.value
                                        )
                                    }
                                    disabled={disabled}
                                    type={
                                        field.field_type === 'bool'
                                            ? 'text'
                                            : 'text'
                                    }
                                    className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-900 outline-none focus:border-sky-500 dark:border-gray-700 dark:bg-[#2d2d2d] dark:text-gray-100"
                                />
                            )}

                            {question?.isOther && (
                                <input
                                    value={values[field.name] || ''}
                                    onChange={(event) =>
                                        updateValue(
                                            field.name,
                                            event.target.value
                                        )
                                    }
                                    disabled={disabled}
                                    placeholder="Other"
                                    className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-900 outline-none focus:border-sky-500 dark:border-gray-700 dark:bg-[#2d2d2d] dark:text-gray-100"
                                />
                            )}
                        </div>
                    )
                })}
            </div>

            <div className="mt-4 flex items-center gap-3">
                <Button
                    onClick={() => onSubmit(values)}
                    disabled={disabled || !allRequiredAnswered}
                    className="bg-sky-600 hover:bg-sky-700 text-white font-medium py-2 px-6 rounded-lg transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {t('common.confirm')}
                </Button>
                <button
                    onClick={onCancel}
                    disabled={disabled}
                    className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                >
                    {t('common.cancel', 'Cancel')}
                </button>
            </div>
        </div>
    )
}

// --- AskUserSelect UI ---

interface AskUserSelectOption {
    value: string
    label: string
}

interface AskUserSelectUIProps {
    toolArgs: Record<string, unknown>
    disabled?: boolean
    onSelect: (selected: string) => void
    onSkip: () => void
}

function AskUserSelectUI({
    toolArgs,
    disabled = false,
    onSelect,
    onSkip
}: AskUserSelectUIProps) {
    const { t } = useTranslation()
    const [selectedValue, setSelectedValue] = useState<string | null>(null)

    const question = (toolArgs.question as string) || ''
    const options = (toolArgs.options as AskUserSelectOption[]) || []

    return (
        <div className="mt-3 w-full max-w-2xl rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#1e1e1e] p-4 shadow-sm">
            {disabled && (
                <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                    {t('agent.toolConfirmation.inactive')}
                </p>
            )}
            <p className="mb-3 text-sm font-medium text-gray-900 dark:text-gray-100">
                {question}
            </p>

            <div className="flex flex-col gap-2">
                {options.map((option, idx) => {
                    const isSelected = selectedValue === option.value
                    return (
                        <button
                            key={idx}
                            onClick={() => {
                                if (!disabled) {
                                    setSelectedValue(option.value)
                                }
                            }}
                            disabled={disabled}
                            className={`group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-all duration-200 ${
                                isSelected
                                    ? 'bg-sky-100 dark:bg-sky-900/30 border border-sky-400 dark:border-sky-600 text-sky-900 dark:text-sky-100'
                                    : 'bg-gray-50 dark:bg-[#2d2d2d] border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#333333]'
                            } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
                        >
                            <span className="flex-1">{option.label}</span>
                            {isSelected && (
                                <Check className="size-4 text-sky-600 dark:text-sky-400" />
                            )}
                        </button>
                    )
                })}
            </div>

            <div className="mt-4 flex items-center gap-3">
                <Button
                    onClick={() => {
                        if (selectedValue) onSelect(selectedValue)
                    }}
                    disabled={disabled || !selectedValue}
                    className="bg-sky-600 hover:bg-sky-700 text-white font-medium py-2 px-6 rounded-lg transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {t('common.confirm')}
                </Button>
                <button
                    onClick={onSkip}
                    disabled={disabled}
                    className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                >
                    {t('common.skip')}
                </button>
            </div>
        </div>
    )
}
