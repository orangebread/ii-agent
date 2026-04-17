import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import type { ComposioProfile, ComposioToolkit } from '@/state/api/composio.api'
import {
    useGetToolkitActionsQuery,
    useUpdateProfileToolsMutation
} from '@/state/api/composio.api'
import { ComposioToolSelector } from './composio-tool-selector'
import { ComposioDisconnectDialog } from './composio-disconnect-dialog'
import { Icon } from '../ui/icon'

interface ComposioManageModalProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    profile: ComposioProfile
    onDisconnect: () => void
    toolkitsData?: ComposioToolkit[]
}

export function ComposioManageModal({
    open,
    onOpenChange,
    profile,
    onDisconnect,
    toolkitsData
}: ComposioManageModalProps) {
    const { t } = useTranslation()
    const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set())
    const [showDisconnectDialog, setShowDisconnectDialog] = useState(false)
    const [hasChanges, setHasChanges] = useState(false)
    const [imageError, setImageError] = useState(false)

    const toolkit = toolkitsData?.find((t) => t.slug === profile.toolkit_slug)
    const showLogo = toolkit?.logo && !imageError

    const { data: actionsData, isLoading } = useGetToolkitActionsQuery(
        profile.toolkit_slug
    )
    const [updateTools, { isLoading: isSaving }] =
        useUpdateProfileToolsMutation()

    // Initialize selected tools from profile
    useEffect(() => {
        if (profile.enabled_tools && profile.enabled_tools.length > 0) {
            // Use saved selection from profile
            setSelectedTools(new Set(profile.enabled_tools))
        } else if (actionsData?.actions) {
            // First time: use default tools from API
            const defaultTools = actionsData.actions
                .filter((action) => action.default_enabled)
                .map((action) => action.name)

            if (defaultTools.length > 0) {
                setSelectedTools(new Set(defaultTools))
            } else {
                // Fallback: all tools enabled if no defaults defined
                setSelectedTools(
                    new Set(actionsData.actions.map((a) => a.name))
                )
            }
        }
    }, [profile.enabled_tools, actionsData])

    const handleSave = async () => {
        try {
            await updateTools({
                profileId: profile.id,
                enabledTools: Array.from(selectedTools)
            }).unwrap()

            toast.success(
                t('composio.manageModal.toasts.toolsEnabled', {
                    count: selectedTools.size,
                    appName: profile.toolkit_name
                })
            )

            setHasChanges(false)
            onOpenChange(false)
        } catch (error: any) {
            toast.error(
                error.message ||
                    t('composio.manageModal.toasts.failedToUpdateTools')
            )
        }
    }

    const handleToolsChange = (newSelection: Set<string>) => {
        setSelectedTools(newSelection)
        setHasChanges(true)
    }

    const handleDisconnectConfirm = async () => {
        try {
            // Call the parent's onDisconnect handler
            await onDisconnect()

            // Close the disconnect dialog
            setShowDisconnectDialog(false)

            // Close the manage modal
            onOpenChange(false)
        } catch (error) {
            // Error is already handled in parent, just close disconnect dialog
            setShowDisconnectDialog(false)
        }
    }

    return (
        <>
            <Sheet open={open} onOpenChange={onOpenChange}>
                <SheetContent
                    className="w-full sm:w-[60vw] lg:w-[60vw] xl:w-[60vw] max-w-none sm:max-w-none p-0 flex flex-col h-full !bg-white border-gray-200"
                    accessibleTitle={profile.toolkit_name}
                    accessibleDescription={t(
                        'composio.manageModal.toolsDescription',
                        {
                            appName: profile.toolkit_name
                        }
                    )}
                >
                    {/* Header */}
                    <div className="px-3 md:px-8 pt-8 pb-6 border-b border-gray-100 flex items-start justify-between">
                        <div className="flex items-start gap-4">
                            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-sky-50 to-blue-50 flex items-center justify-center shadow-sm ring-1 ring-sky-100 overflow-hidden">
                                {showLogo ? (
                                    <img
                                        src={toolkit?.logo}
                                        alt={`${profile.toolkit_name} logo`}
                                        className="h-full w-full object-cover"
                                        onError={() => setImageError(true)}
                                    />
                                ) : (
                                    <span className="text-2xl font-semibold text-sky-600">
                                        {profile.toolkit_name[0]}
                                    </span>
                                )}
                            </div>
                            <div className="flex-1 min-w-0">
                                <SheetTitle className="text-2xl font-semibold tracking-tight text-gray-900 mb-1.5">
                                    {profile.toolkit_name}
                                </SheetTitle>
                                <div className="flex items-center gap-2">
                                    <Badge
                                        className={`px-2.5 py-0.5 text-xs font-medium ${
                                            profile.status === 'enable'
                                                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                                : profile.status === 'disable'
                                                  ? 'bg-gray-50 text-gray-700 border-gray-200'
                                                  : 'bg-amber-50 text-amber-700 border-amber-200'
                                        }`}
                                    >
                                        ●{' '}
                                        {profile.status === 'enable'
                                            ? t(
                                                  'composio.manageModal.status.connected'
                                              )
                                            : profile.status === 'disable'
                                              ? t(
                                                    'composio.manageModal.status.disabled'
                                                )
                                              : t(
                                                    'composio.manageModal.status.disconnected'
                                                )}
                                    </Badge>
                                    <span className="text-sm text-gray-500">
                                        {profile.profile_name}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <button
                            className="cursor-pointer"
                            onClick={() => onOpenChange(false)}
                        >
                            <Icon
                                name="close-2"
                                className="size-6 text-black"
                            />
                        </button>
                    </div>

                    {/* Content */}
                    <div className="flex-1 overflow-y-auto px-3 md:px-8 py-6">
                        <div className="mb-6">
                            <h3 className="text-base font-semibold text-gray-900 mb-1">
                                {t('composio.manageModal.toolsAndPermissions')}
                            </h3>
                            <p className="text-sm text-gray-500 leading-relaxed">
                                {t('composio.manageModal.toolsDescription', {
                                    appName: profile.toolkit_name
                                })}
                            </p>
                        </div>

                        {isLoading ? (
                            <div className="space-y-3">
                                {[1, 2, 3].map((i) => (
                                    <div
                                        key={i}
                                        className="h-16 bg-gradient-to-r from-gray-50 to-gray-100 rounded-xl animate-pulse"
                                    />
                                ))}
                            </div>
                        ) : actionsData ? (
                            <ComposioToolSelector
                                actions={actionsData.actions}
                                categories={actionsData.categories}
                                selectedTools={selectedTools}
                                onSelectionChange={handleToolsChange}
                            />
                        ) : null}
                    </div>

                    {/* Footer */}
                    <div className="px-8 py-6 border-t border-gray-100 bg-gray-50/50">
                        <div className="flex items-center gap-3">
                            <Button
                                onClick={handleSave}
                                disabled={!hasChanges || isSaving}
                                className="flex-1 h-11 bg-sky-blue text-black font-medium shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                            >
                                {isSaving ? (
                                    <span className="flex items-center gap-2">
                                        <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                        {t('composio.manageModal.saving')}
                                    </span>
                                ) : (
                                    t('composio.manageModal.saveChanges')
                                )}
                            </Button>
                            <Button
                                variant="outline"
                                onClick={() => setShowDisconnectDialog(true)}
                                disabled={isSaving}
                                className="h-11 px-5 border-red-200 text-red-600 hover:bg-red-50 hover:border-red-300 font-medium transition-all"
                            >
                                {t('composio.manageModal.disconnect')}
                            </Button>
                        </div>
                    </div>
                </SheetContent>
            </Sheet>

            <ComposioDisconnectDialog
                open={showDisconnectDialog}
                onOpenChange={setShowDisconnectDialog}
                profile={profile}
                onConfirm={handleDisconnectConfirm}
            />
        </>
    )
}
