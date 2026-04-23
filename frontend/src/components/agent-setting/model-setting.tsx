import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'

import {
    PROVIDERS_NAME,
    getPreferredModelIdForFeature,
    getProviderKey,
    getRuntimeProductLabel,
    getSelectableModels,
    getSelectableModelsForFeature,
    getVisibleModelsForFeature,
    isSelectableModel
} from '@/constants/models'
import { useAppDispatch, useAppSelector } from '@/state/store'
import {
    selectSelectedFeature,
    selectSelectedModel,
    setAvailableModels,
    setSelectedModel
} from '@/state'
import { IModel, IMcpSettings } from '@/typings/settings'
import { settingsService } from '@/services/settings.service'
import { hasCodexAuth } from '@/lib/codex'
import { Button } from '../ui/button'
import { Icon } from '../ui/icon'
import AddEditModel from './add-edit-model'

interface ModelSettingProps {
    className?: string
    isActive?: boolean
}

const ModelSetting = ({ className, isActive = false }: ModelSettingProps) => {
    const { t } = useTranslation()
    const dispatch = useAppDispatch()

    const [isAddEditModelOpen, setIsAddEditModelOpen] = useState(false)
    const [editingModel, setEditingModel] = useState<IModel | null>(null)
    const [modelInventory, setModelInventory] = useState<IModel[]>([])
    const [isLoadingInventory, setIsLoadingInventory] = useState(false)
    const [codexSetting, setCodexSetting] = useState<IMcpSettings | null>(null)
    const [claudeCodeSetting, setClaudeCodeSetting] =
        useState<IMcpSettings | null>(null)

    const selectedModel = useAppSelector(selectSelectedModel)
    const selectedFeature = useAppSelector(selectSelectedFeature)

    const visibleModels = useMemo(
        () => getVisibleModelsForFeature(modelInventory, selectedFeature),
        [modelInventory, selectedFeature]
    )

    const selectableModels = useMemo(
        () => getSelectableModelsForFeature(modelInventory, selectedFeature),
        [modelInventory, selectedFeature]
    )

    const syncSelectableModels = (
        inventory: IModel[],
        preferredModelId?: string
    ) => {
        const nextSelectableModels = getSelectableModels(inventory)
        dispatch(setAvailableModels(nextSelectableModels))

        const currentSelectedId = preferredModelId ?? selectedModel
        const nextSelectedModelId = getPreferredModelIdForFeature(
            nextSelectableModels,
            selectedFeature,
            currentSelectedId
        )
        dispatch(setSelectedModel(nextSelectedModelId))
    }

    const fetchModelInventory = async (preferredModelId?: string) => {
        try {
            setIsLoadingInventory(true)
            const [availableModelsResponse, nextCodexSetting, nextClaudeSetting] =
                await Promise.all([
                    settingsService.getAvailableModels(),
                    settingsService.getCodexSettings(),
                    settingsService.getClaudeCodeSettings()
                ])

            const nextInventory = availableModelsResponse?.models || []
            setModelInventory(nextInventory)
            setCodexSetting(nextCodexSetting)
            setClaudeCodeSetting(nextClaudeSetting)
            syncSelectableModels(nextInventory, preferredModelId)
        } catch (error) {
            console.error('Failed to fetch model inventory:', error)
        } finally {
            setIsLoadingInventory(false)
        }
    }

    useEffect(() => {
        if (!isActive) {
            return
        }
        void fetchModelInventory()
    }, [isActive])

    useEffect(() => {
        if (modelInventory.length === 0) {
            return
        }
        syncSelectableModels(modelInventory)
    }, [modelInventory, selectedFeature])

    const saveConfig = async (model: IModel, isEdit: boolean) => {
        await fetchModelInventory(model.id)
        setIsAddEditModelOpen(false)
        toast.success(
            isEdit
                ? t('agentSetting.modelSetting.toasts.updated')
                : t('agentSetting.modelSetting.toasts.created')
        )
    }

    const handleDelete = async (modelToDelete: string) => {
        try {
            await settingsService.deleteModel(modelToDelete)
            await fetchModelInventory()
            toast.success(t('agentSetting.modelSetting.toasts.deleted'))
        } catch (error) {
            console.error('Error deleting model:', error)
            toast.error(t('agentSetting.modelSetting.toasts.deleteFailed'))
        }
    }

    const handleEdit = (model: IModel) => {
        setEditingModel(model)
        setIsAddEditModelOpen(true)
    }

    const handleCloseAddEdit = () => {
        setIsAddEditModelOpen(false)
        setEditingModel(null)
    }

    const emptyState = useMemo(() => {
        if (selectableModels.length > 0) {
            return null
        }

        if (selectedFeature === 'claude_code') {
            if (claudeCodeSetting?.metadata?.needs_reauth) {
                return {
                    title: 'Reconnect Claude Code',
                    body: 'Your Anthropic Claude OAuth connection is no longer usable. Reconnect it, then reopen this tab.'
                }
            }

            if (claudeCodeSetting?.metadata?.has_auth) {
                return {
                    title: 'Claude Code models are not ready yet',
                    body: 'Claude Code is connected, but there is still no selectable Claude-backed model. Refresh this tab, and if it stays empty the backend has not materialized a runnable model row.'
                }
            }
        }

        if (selectedFeature === 'codex') {
            if (hasCodexAuth(codexSetting)) {
                return {
                    title: 'Codex models are not ready yet',
                    body: 'Codex is connected, but there is still no selectable Codex-backed model. Refresh this tab, and if it stays empty the backend has not materialized a runnable model row.'
                }
            }
        }

        if (claudeCodeSetting?.metadata?.needs_reauth) {
            return {
                title: 'Reconnect Claude OAuth',
                body: 'Your Anthropic Claude OAuth connection is no longer usable for model execution. Reconnect it, then reopen this tab.'
            }
        }

        if (claudeCodeSetting?.metadata?.has_auth) {
            return {
                title: 'Claude models are not ready yet',
                body: 'Anthropic OAuth finished, but there is still no selectable Claude model. Refresh this tab, and if it stays empty the backend has not materialized a runnable model row.'
            }
        }

        if (hasCodexAuth(codexSetting)) {
            return {
                title: 'Codex is connected, but no model is selectable yet',
                body: 'Codex OAuth succeeded, but there is still no selectable Codex-backed model in this inventory. Refresh this tab, and if it stays empty the backend has not materialized a runnable model row.'
            }
        }

        return {
            title: 'No selectable models yet',
            body: 'Add a model with an API key or connect Codex or Claude Code OAuth. Once a runnable model exists, it will appear here.'
        }
    }, [claudeCodeSetting, codexSetting, selectableModels.length, selectedFeature])

    return (
        <div className={`space-y-4 ${className}`}>
            <p className="text-lg font-semibold dark:text-white">
                {t('agentSetting.modelSetting.title')}
            </p>

            {emptyState && (
                <div className="rounded-2xl border border-firefly/15 bg-firefly/5 p-4 dark:border-sky-blue-2/25 dark:bg-sky-blue-2/10">
                    <p className="text-sm font-semibold dark:text-white">
                        {emptyState.title}
                    </p>
                    <p className="mt-2 text-sm text-black/70 dark:text-white/70">
                        {emptyState.body}
                    </p>
                </div>
            )}

            {isLoadingInventory && visibleModels.length === 0 && (
                <div className="rounded-2xl border border-dashed border-firefly/20 p-4 text-sm text-black/70 dark:border-sky-blue-2/25 dark:text-white/70">
                    Loading model inventory...
                </div>
            )}

            {visibleModels.map((model) => {
                const providerKey = getProviderKey(model)
                const isModelSelectable = isSelectableModel(model)
                const isCurrentSelection =
                    isModelSelectable && selectedModel === model.id
                const canEditModel =
                    model.source !== 'system' && model.is_managed !== true
                const runtimeProductLabel = getRuntimeProductLabel(model)

                return (
                    <div
                        key={model.id}
                        className={`flex min-h-[88px] items-center justify-between rounded-2xl transition-colors ${
                            isCurrentSelection
                                ? 'border-2 border-firefly bg-sky-blue p-[14px] dark:border-sky-blue-2 dark:bg-sky-blue-2/20'
                                : 'bg-firefly/10 p-4 dark:bg-sky-blue-2/5'
                        } ${
                            isModelSelectable
                                ? 'cursor-pointer'
                                : 'cursor-not-allowed opacity-80'
                        }`}
                        onClick={() => {
                            if (!isModelSelectable) {
                                return
                            }
                            dispatch(setSelectedModel(model.id))
                        }}
                    >
                        <div className="flex items-center gap-x-4">
                            <div className="flex size-[46px] items-center justify-center rounded-full">
                                {PROVIDERS_NAME[providerKey] && (
                                    <img
                                        src={`/images/${providerKey}.svg`}
                                        alt={providerKey}
                                        className="size-[46px] object-contain"
                                    />
                                )}
                            </div>
                            <div>
                                <div className="flex items-center gap-x-2">
                                    <p className="text-base font-semibold dark:text-white">
                                        {model.display_name ||
                                            PROVIDERS_NAME[providerKey]}
                                    </p>
                                    {runtimeProductLabel && (
                                        <span className="rounded-full bg-firefly/10 px-2 py-0.5 text-xs text-firefly dark:bg-sky-blue-2/15 dark:text-sky-blue-2">
                                            {runtimeProductLabel}
                                        </span>
                                    )}
                                    {model.is_managed && (
                                        <span className="rounded-full bg-firefly/10 px-2 py-0.5 text-xs text-firefly dark:bg-sky-blue-2/15 dark:text-sky-blue-2">
                                            Managed
                                        </span>
                                    )}
                                </div>
                                <p className="mt-1 text-sm dark:text-white">
                                    {model.model_id || model.model}
                                </p>
                                {!isModelSelectable && model.disabled_reason && (
                                    <p className="mt-1 text-xs text-black/60 dark:text-white/60">
                                        {model.disabled_reason}
                                    </p>
                                )}
                            </div>
                        </div>
                        {canEditModel && (
                            <div className="flex items-center gap-x-4">
                                <Button
                                    className="size-6 p-0"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        handleEdit(model)
                                    }}
                                >
                                    <Icon
                                        name="edit-2"
                                        className="size-6 fill-firefly dark:fill-sky-blue-2"
                                    />
                                </Button>
                                <Button
                                    className="size-6 p-0"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        handleDelete(model.id)
                                    }}
                                >
                                    <Icon name="trash" />
                                </Button>
                            </div>
                        )}
                    </div>
                )
            })}

            <Button
                variant="outline"
                className="rounded-xl px-6 font-normal text-black dark:text-white"
                onClick={() => setIsAddEditModelOpen(true)}
            >
                <Icon
                    name="add-square"
                    className="fill-black dark:fill-white"
                />{' '}
                {t('agentSetting.modelSetting.actions.newModel')}
            </Button>
            <AddEditModel
                open={isAddEditModelOpen}
                onOpenChange={handleCloseAddEdit}
                onSaveConfig={saveConfig}
                editingModel={editingModel}
            />
        </div>
    )
}

export default ModelSetting
