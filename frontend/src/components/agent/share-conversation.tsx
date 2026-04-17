import { useMemo, useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Link, useParams } from 'react-router'
import { Trans, useTranslation } from 'react-i18next'

import { Icon } from '../ui/icon'
import { Sheet, SheetClose, SheetContent, SheetHeader } from '../ui/sheet'
import { Button } from '../ui/button'
import { sessionService } from '@/services/session.service'
import { storybookService, type Storybook } from '@/services/storybook.service'
import { ISession } from '@/typings/agent'

interface ShareConversationProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    sessionId?: string
    sessionData?: ISession
    storybookId?: string
}

const ShareConversation = ({
    open,
    onOpenChange,
    sessionId: propSessionId,
    sessionData,
    storybookId
}: ShareConversationProps) => {
    const { t } = useTranslation()
    const { sessionId: paramsSessionId } = useParams()
    const sessionId = propSessionId || paramsSessionId
    const [isPublished, setIsPublished] = useState(false)
    const [agentType, setAgentType] = useState<string | null>(
        sessionData?.agent_type || null
    )
    const [sessionStorybookId, setSessionStorybookId] = useState<
        string | undefined
    >(storybookId)

    useEffect(() => {
        const fetchSessionData = async () => {
            if (!sessionId) return

            try {
                const session = await sessionService.getSession(sessionId)
                setIsPublished(session.is_public || false)
                if (session.agent_type) {
                    setAgentType(session.agent_type)
                }
            } catch (error) {
                console.error('Error fetching session data:', error)
            }
        }

        if (open && sessionId) {
            fetchSessionData()
        }
    }, [sessionId, open])

    useEffect(() => {
        if (storybookId) {
            setSessionStorybookId(storybookId)
        }
    }, [storybookId])

    useEffect(() => {
        if (!open || !sessionId || storybookId) return

        let isActive = true

        const parseTime = (value?: string | null) => {
            if (!value) return 0
            const parsed = Date.parse(value)
            return Number.isNaN(parsed) ? 0 : parsed
        }

        const pickLatestStorybook = (storybooks: Storybook[]) => {
            if (storybooks.length === 0) return undefined

            return storybooks.reduce((latest, current) => {
                const latestTime = Math.max(
                    parseTime(latest.updated_at),
                    parseTime(latest.created_at)
                )
                const currentTime = Math.max(
                    parseTime(current.updated_at),
                    parseTime(current.created_at)
                )

                if (currentTime > latestTime) return current
                if (currentTime < latestTime) return latest
                if ((current.version || 0) > (latest.version || 0)) {
                    return current
                }
                return latest
            }, storybooks[0])
        }

        const fetchStorybooks = async () => {
            try {
                const response =
                    await storybookService.getSessionStorybooks(sessionId)
                const latest = pickLatestStorybook(response.storybooks || [])
                if (isActive) {
                    setSessionStorybookId(latest?.id)
                }
            } catch (error) {
                console.error('Error fetching storybooks:', error)
                if (isActive) {
                    setSessionStorybookId(undefined)
                }
            }
        }

        fetchStorybooks()

        return () => {
            isActive = false
        }
    }, [open, sessionId, storybookId])

    const shareUrl = useMemo(() => {
        return `${window.location.origin}/share/${sessionId}`
    }, [sessionId])

    const presentationUrl = useMemo(() => {
        return `${window.location.origin}/presentations/${sessionId}`
    }, [sessionId])

    const storybookUrl = useMemo(() => {
        return sessionStorybookId
            ? `${window.location.origin}/storybooks/${sessionStorybookId}`
            : ''
    }, [sessionStorybookId])

    const isSlideSession = useMemo(
        () => agentType === 'slide' || agentType === 'slide_nano_banana',
        [agentType]
    )

    const handleCopy = () => {
        navigator.clipboard.writeText(shareUrl)
        toast.success(t('common.copiedToClipboard'))
    }

    const handleCopyPresentationUrl = () => {
        navigator.clipboard.writeText(presentationUrl)
        toast.success(t('common.copiedToClipboard'))
    }

    const handleCopyStorybookUrl = () => {
        if (!storybookUrl) return
        navigator.clipboard.writeText(storybookUrl)
        toast.success(t('common.copiedToClipboard'))
    }

    const handlePublish = async () => {
        if (!sessionId) {
            toast.error(t('share.sessionIdNotFound'))
            return
        }

        try {
            await sessionService.publishSession(sessionId)
            setIsPublished(true)
            toast.success(t('share.publishSuccess'))
        } catch (error) {
            toast.error(t('share.publishError'))
            console.error('Error publishing session:', error)
        }
    }

    const handleUnpublish = async () => {
        if (!sessionId) {
            toast.error(t('share.sessionIdNotFound'))
            return
        }

        try {
            await sessionService.unpublishSession(sessionId)
            setIsPublished(false)
            toast.success(t('share.unpublishSuccess'))
        } catch (error) {
            toast.error(t('share.unpublishError'))
            console.error('Error unpublishing session:', error)
        }
    }

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                className="!left-1/2 !top-1/2 !right-auto !bottom-auto !h-auto !max-h-[90vh] !w-[92vw] !max-w-[650px] !-translate-x-1/2 !-translate-y-1/2 !rounded-2xl !p-0 shadow-2xl !bg-white !text-slate-900 dark:!bg-white dark:!text-slate-900"
                accessibleTitle={t('share.title')}
            >
                <SheetHeader className="px-6 pt-6 gap-1 pb-4 text-slate-900">
                    <div className="flex items-center justify-between">
                        <p className="text-lg font-semibold text-slate-900">
                            {t('share.title')}
                        </p>
                        <div className="flex items-center gap-x-4">
                            <SheetClose className="cursor-pointer">
                                <Icon
                                    name="close"
                                    className="fill-grey-2 size-5"
                                />
                            </SheetClose>
                        </div>
                    </div>
                </SheetHeader>
                <div className="px-6 pb-6 space-y-4">
                    {isPublished ? (
                        <>
                            <div className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                                <div className="flex items-center gap-2 text-sm text-slate-700 min-w-0">
                                    <Icon
                                        name="link-2"
                                        className="size-6 fill-black -rotate-45"
                                    />
                                    <span className="line-clamp-1">
                                        {shareUrl}
                                    </span>
                                </div>
                                <Button
                                    className="h-8 px-4 rounded-lg bg-sky-blue text-black text-sm font-medium"
                                    onClick={handleCopy}
                                >
                                    {t('common.copy')}
                                </Button>
                            </div>

                            <div className="flex items-start gap-2 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3">
                                <Icon
                                    name="light-bulb"
                                    className="size-10 pb-4"
                                />
                                <p className="text-sm text-slate-700">
                                    <Trans
                                        i18nKey="share.publicLinkDescription"
                                        components={{
                                            settingsLink: (
                                                <Link
                                                    to="/settings/data-controls"
                                                    className="underline"
                                                />
                                            )
                                        }}
                                    />
                                </p>
                            </div>

                            {/* Presentation Link Section for slide sessions */}
                            {isSlideSession && (
                                <>
                                    <div className="pt-4 border-t border-slate-200">
                                        <p className="text-sm font-semibold text-slate-900">
                                            {t('share.presentationLink')}
                                        </p>
                                        <p className="text-xs mt-1 text-slate-600">
                                            {t(
                                                'share.presentationLinkDescription'
                                            )}
                                        </p>
                                        <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                                            <div className="flex items-center gap-x-2 text-sm text-slate-700 min-w-0">
                                                <Icon
                                                    name="presentation"
                                                    className="size-4 fill-slate-500"
                                                />
                                                <span className="line-clamp-1">
                                                    {presentationUrl}
                                                </span>
                                            </div>
                                            <Button
                                                className="h-8 px-4 rounded-lg bg-sky-blue text-black text-sm font-medium"
                                                onClick={
                                                    handleCopyPresentationUrl
                                                }
                                            >
                                                {t('common.copy')}
                                            </Button>
                                        </div>
                                    </div>
                                </>
                            )}

                            {/* Storybook Link Section */}
                            {sessionStorybookId && (
                                <>
                                    <div className="pt-4 border-t border-slate-200">
                                        <p className="text-sm font-semibold text-slate-900">
                                            {t('share.storybookLink')}
                                        </p>
                                        <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                                            <div className="flex items-center gap-x-2 text-sm text-slate-700 min-w-0">
                                                <Icon
                                                    name="mode-storybook"
                                                    className="size-4 fill-slate-500"
                                                />
                                                <span className="line-clamp-1">
                                                    {storybookUrl}
                                                </span>
                                            </div>
                                            <Button
                                                className="h-8 px-4 rounded-lg bg-sky-blue text-black text-sm font-medium"
                                                onClick={handleCopyStorybookUrl}
                                            >
                                                {t('common.copy')}
                                            </Button>
                                        </div>
                                    </div>
                                </>
                            )}

                            <Button
                                size="xl"
                                className="mt-2 w-full bg-red-2 font-semibold"
                                onClick={handleUnpublish}
                            >
                                <Icon
                                    name="link-2"
                                    className="size-6 fill-black"
                                />
                                {t('share.unpublish')}
                            </Button>
                        </>
                    ) : (
                        <>
                            <div className="flex items-start gap-3 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3">
                                <Icon
                                    name="info-circle"
                                    className="size-5 fill-sky-500 mt-0.5"
                                />
                                <p className="text-sm text-slate-700">
                                    {t('share.privateNote')}
                                </p>
                            </div>
                            <Button
                                size="xl"
                                className="w-full bg-sky-blue text-black font-semibold"
                                onClick={handlePublish}
                            >
                                <Icon
                                    name="link-2"
                                    className="size-6 fill-black"
                                />
                                {t('share.createLink')}
                            </Button>
                        </>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    )
}

export default ShareConversation
