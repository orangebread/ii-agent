import { useEffect, useState } from 'react'

import { mediaToolsService } from '@/services/media-tools.service'
import { type MiniTool } from '@/constants/media-tools'
import { Icon } from '../../ui/icon'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useWindowSize } from '@/hooks/use-window-size'
import { useTranslation } from 'react-i18next'
import { useIsMobile } from '@/hooks/use-mobile'

type Props = {
    open: boolean
    disabled?: boolean
    onSelect: (tool: MiniTool) => void
    onClose: () => void
}

/**
 * A simplified Mini Tools grid for use without a session (e.g., home page).
 * Only displays the tool selection grid, no upload/library features.
 */
const MiniToolsGrid = ({ open, disabled, onSelect, onClose }: Props) => {
    const { t } = useTranslation()
    const toolNameMap = t('media.miniTools.toolNames', {
        returnObjects: true
    }) as Record<string, string>
    const [tools, setTools] = useState<MiniTool[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [modalWidth, setModalWidth] = useState(0)
    const [modelLeft, setModelLeft] = useState(0)
    const windowWidth = useWindowSize()
    const isMobile = useIsMobile()

    useEffect(() => {
        let mounted = true
        setLoading(true)
        mediaToolsService
            .listMediaTools()
            .then((res) => {
                if (mounted) setTools(res)
            })
            .catch((err) => {
                console.error('Failed to load mini tools', err)
                if (mounted) setError(t('media.miniTools.loadError') as string)
            })
            .finally(() => {
                if (mounted) setLoading(false)
            })
        return () => {
            mounted = false
        }
    }, [t])

    const renderPreview = (tool: MiniTool, toolLabel: string) => {
        if (tool.preview) {
            return (
                <div className="flex h-full w-full items-center justify-center rounded-[18px] md:px-6">
                    <div className="h-full w-full overflow-hidden rounded-[14px] object-top">
                        <img
                            src={tool.preview}
                            alt={toolLabel}
                            className="h-full w-full object-contain"
                        />
                    </div>
                </div>
            )
        }

        return (
            <div className="flex h-full w-full items-center justify-center rounded-[18px] bg-[#eef2f6] p-3 dark:bg-[#0f1f26]">
                <div className="grid w-full grid-cols-2 items-center gap-3 rounded-[14px] bg-white p-3 shadow-[0_12px_32px_rgba(0,0,0,0.18)] dark:bg-[#15232d]">
                    <div className="relative aspect-[3/4] w-full rounded-lg bg-gradient-to-br from-[#dcdfe5] via-white to-[#c7ccd4] dark:from-[#1f2b34] dark:via-[#0f1f26] dark:to-[#24323c]">
                        <span className="absolute inset-x-0 bottom-1 text-center text-[10px] font-semibold text-[#212121] dark:text-white">
                            {t('media.miniTools.before')}
                        </span>
                    </div>
                    <div className="relative aspect-[3/4] w-full rounded-lg bg-gradient-to-br from-[#dfeafc] via-white to-[#bad8ff] dark:from-[#1d2f3d] dark:via-[#0f1f26] dark:to-[#1f3d52]">
                        <span className="absolute inset-x-0 bottom-1 text-center text-[10px] font-semibold text-[#212121] dark:text-white">
                            {t('media.miniTools.after')}
                        </span>
                    </div>
                </div>
            </div>
        )
    }

    const handleSelect = (tool: MiniTool) => {
        onSelect(tool)
    }

    useEffect(() => {
        const homeContainer = document.getElementById('home-container')
        if (homeContainer) {
            setModalWidth(homeContainer.clientWidth)
            setModelLeft(
                homeContainer.offsetLeft > 30 ? homeContainer.offsetLeft : 0
            )
        }
    }, [windowWidth, isMobile, open])

    return (
        <Dialog open={open}>
            <DialogContent
                hideDialogOverlay
                showCloseButton={false}
                className="w-full md:w-[calc(100vw-178px)] overflow-auto !translate-x-0 group-data-[collapsible=icon]:w-[calc(100vw-345px)] h-full dark:bg-charcoal border-none shadow-none !max-w-none"
                accessibleTitle={t('media.miniTools.chooseTool')}
                style={
                    isMobile
                        ? {
                              width: '100vw',
                              left: 0,
                              backgroundImage: 'url(/images/bg.png)',
                              backgroundSize: 'cover',
                              backgroundRepeat: 'no-repeat',
                              backgroundPosition: 'center'
                          }
                        : {
                              width: `${modalWidth}px`,
                              left: `${modelLeft}px`
                          }
                }
            >
                {/* Back / Header */}
                <div className="mb-6 md:mb-10 flex w-full items-center justify-center">
                    <button
                        type="button"
                        onClick={onClose}
                        className="cursor-pointer flex items-center gap-2 px-4 text-sm font-semibold transition-all hover:-translate-y-0.5"
                    >
                        <span>{t('media.miniTools.back')}</span>
                        <span
                            className={`inline-flex items-center justify-center w-5 h-5 rounded-full rotate-180`}
                        >
                            <Icon
                                name="arrow-up-2"
                                className="size-5 fill-current"
                            />
                        </span>
                    </button>
                </div>

                {/* Loading state - Skeleton */}
                {loading && (
                    <div className="w-full md:w-auto mx-auto flex flex-col gap-6">
                        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
                            {Array.from({ length: 12 }).map((_, index) => (
                                <div
                                    key={index}
                                    className="relative flex flex-col rounded-xl bg-sky-blue/30 w-full md:w-[300px] h-[220px] pb-6 animate-pulse"
                                >
                                    <div className="flex h-full w-full items-center justify-center rounded-[18px] p-3 md:px-6">
                                        <div className="h-full w-full rounded-[14px] bg-gray-300/50 dark:bg-gray-700/50" />
                                    </div>
                                    <div className="absolute w-full left-1/2 -translate-x-1/2 bottom-4 flex justify-center">
                                        <div className="h-4 w-24 rounded bg-gray-300/50 dark:bg-gray-700/50" />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Error state */}
                {error && (
                    <div className="py-12 text-center text-sm text-red-500 dark:text-red-400">
                        {error}
                    </div>
                )}

                {/* Tools Grid */}
                {!loading && !error && (
                    <div className="mx-auto flex flex-col gap-6">
                        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
                            {tools.map((tool) => {
                                const toolLabel =
                                    toolNameMap?.[tool.name] ?? tool.name

                                return (
                                    <button
                                        key={tool.id}
                                        onClick={() => handleSelect(tool)}
                                        className="relative cursor-pointer group flex w-full flex-col rounded-xl bg-sky-blue/30 hover:bg-sky-blue max-h-[220px] pb-6"
                                        disabled={disabled}
                                    >
                                        {renderPreview(tool, toolLabel)}
                                        <span
                                            className="px-1 absolute w-full left-1/2 -translate-x-1/2 bottom-4 md:bottom-6 text-center text-xs md:text-sm font-semibold leading-tight text-[#0b1218] dark:text-white group-hover:text-black"
                                            title={toolLabel}
                                        >
                                            {toolLabel}
                                        </span>
                                    </button>
                                )
                            })}
                        </div>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    )
}

export default MiniToolsGrid
