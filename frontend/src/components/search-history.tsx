import { useMemo, useState, useRef, useCallback, useEffect } from 'react'
import dayjs from 'dayjs'
import { Link, useNavigate } from 'react-router'
import isSameOrAfter from 'dayjs/plugin/isSameOrAfter'
dayjs.extend(isSameOrAfter)

import { Icon } from './ui/icon'
import { Input } from './ui/input'
import {
    Sheet,
    SheetClose,
    SheetContent,
    SheetHeader,
    SheetTrigger
} from './ui/sheet'
import { Button } from './ui/button'
import { cn } from '@/lib/utils'
import { useTranslation } from 'react-i18next'
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger
} from '@/components/ui/tooltip'
import {
    setMessages,
    selectSessions,
    selectSessionsLoading,
    selectSessionsHasMore,
    selectSessionsPage,
    selectSessionsLimit,
    fetchSessions,
    resetPagination,
    useAppDispatch,
    useAppSelector,
    setBuildStep,
    setActiveTab,
    setRunStatus,
    setAgentInitialized,
    setShouldFocusInput,
    setRequireClearFiles,
    setIsMobileChatVisible,
    setChatMediaPreference,
    clearCurrentMessageFileIds,
    selectChatMediaPreference
} from '@/state'
import { BUILD_STEP, TAB } from '@/typings/agent'
import { getDefaultChatMediaPreference } from '@/utils/default-models'
import { useMediaModels } from '@/hooks/use-media-models'
import { useSidebar } from '@/components/ui/sidebar'
import { useSessionStateManager } from '@/hooks/use-session-state-manager'
import { useChat } from '@/hooks/use-chat-query'
import SessionTitle from '@/components/session-title'
import { hasSessionDisplayTitle } from '@/utils/session-title'

interface SearchHistoryProps {
    className?: string
    isMobile?: boolean
}

const SearchHistory = ({ className, isMobile }: SearchHistoryProps) => {
    const [open, setOpen] = useState(false)
    const [loadingMore, setLoadingMore] = useState(false)
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const { t } = useTranslation()
    const { isMobile: isSidebarMobile, state } = useSidebar()
    const { resetSessionState } = useSessionStateManager()
    const { resetConversationState, setSessionId } = useChat()

    const navigate = useNavigate()
    const dispatch = useAppDispatch()
    const { imageModels, videoModels } = useMediaModels()
    const sessions = useAppSelector(selectSessions)
    const isLoading = useAppSelector(selectSessionsLoading)
    const hasMore = useAppSelector(selectSessionsHasMore)
    const currentPage = useAppSelector(selectSessionsPage)
    const limit = useAppSelector(selectSessionsLimit)
    const chatMediaPreference = useAppSelector(selectChatMediaPreference)

    const [searchTerm, setSearchTerm] = useState('')

    const groupedSessions = useMemo(() => {
        const now = dayjs()
        const startOfToday = now.startOf('day')
        const startOfYesterday = startOfToday.subtract(1, 'day')
        const start7DaysAgo = startOfToday.subtract(7, 'days')

        const filteredSessions = [...sessions].filter((session) => {
            if (session.name) {
                return session.name
                    .toLowerCase()
                    .includes(searchTerm.toLowerCase())
            }
            return session.title_pending && searchTerm.length === 0
        })

        const todaySessions = filteredSessions.filter((session) => {
            return dayjs(session.created_at).isSame(startOfToday, 'day')
        })

        const yesterdaySessions = filteredSessions.filter((session) => {
            return dayjs(session.created_at).isSame(startOfYesterday, 'day')
        })

        const last7DaysSessions = filteredSessions.filter((session) => {
            const sessionDate = dayjs(session.created_at)
            return (
                sessionDate.isBefore(startOfYesterday) &&
                sessionDate.isSameOrAfter(start7DaysAgo)
            )
        })

        const last30DaysSessions = filteredSessions.filter((session) => {
            const sessionDate = dayjs(session.created_at)
            return sessionDate.isBefore(start7DaysAgo)
        })

        return {
            today: todaySessions,
            yesterday: yesterdaySessions,
            last_7_days: last7DaysSessions,
            last_30_days: last30DaysSessions
        }
    }, [sessions, searchTerm])

    const handleNewChat = () => {
        resetSessionState()
        resetConversationState()
        setSessionId(null)
        dispatch(setMessages([]))
        dispatch(setRunStatus(null))
        dispatch(setActiveTab(TAB.BUILD))
        dispatch(setIsMobileChatVisible(true))
        dispatch(setBuildStep(BUILD_STEP.THINKING))
        dispatch(setAgentInitialized(false))
        dispatch(setShouldFocusInput(true))
        dispatch(setRequireClearFiles(true))
        dispatch(clearCurrentMessageFileIds())
        dispatch(
            setChatMediaPreference(
                getDefaultChatMediaPreference(
                    imageModels,
                    videoModels,
                    chatMediaPreference
                )
            )
        )
        setOpen(false)
        navigate('/')
    }

    // Initialize sessions when sheet opens
    useEffect(() => {
        if (open) {
            dispatch(resetPagination())
            dispatch(fetchSessions({ page: 1, limit }))
        }
    }, [open, dispatch, limit])

    // Handle infinite scroll
    const handleScroll = useCallback(() => {
        if (
            !scrollContainerRef.current ||
            loadingMore ||
            !hasMore ||
            isLoading
        ) {
            return
        }

        const { scrollTop, scrollHeight, clientHeight } =
            scrollContainerRef.current

        // Load more when user scrolls to within 100px of the bottom
        if (scrollHeight - scrollTop - clientHeight < 100) {
            setLoadingMore(true)
            dispatch(fetchSessions({ page: currentPage + 1, limit })).finally(
                () => setLoadingMore(false)
            )
        }
    }, [dispatch, currentPage, limit, hasMore, isLoading, loadingMore])

    useEffect(() => {
        const scrollContainer = scrollContainerRef.current
        if (!scrollContainer) return

        scrollContainer.addEventListener('scroll', handleScroll)
        return () => scrollContainer.removeEventListener('scroll', handleScroll)
    }, [handleScroll])

    return (
        <Sheet open={open} onOpenChange={setOpen}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <SheetTrigger
                        aria-label={t('searchHistory.trigger')}
                        className={`${className} group-data-[collapsible=icon]:w-10`}
                    >
                        {isMobile ? (
                            <Icon
                                name="search-status"
                                className="size-6 fill-black dark:fill-white"
                            />
                        ) : (
                            <div className="flex items-center gap-x-2 font-normal cursor-pointer group-data-[collapsible=icon]:p-0 group-data-[collapsible=icon]:justify-center">
                                <Icon
                                    name="search-status"
                                    className="fill-black dark:fill-white"
                                />
                                <span className="group-data-[collapsible=icon]:hidden">
                                    {t('searchHistory.trigger')}
                                </span>
                            </div>
                        )}
                    </SheetTrigger>
                </TooltipTrigger>
                <TooltipContent
                    side="right"
                    align="center"
                    hidden={state !== 'collapsed' || isSidebarMobile}
                >
                    {t('searchHistory.trigger')}
                </TooltipContent>
            </Tooltip>
            <SheetContent
                side="left"
                className="p-3 md:px-6 md:pt-12 w-full !max-w-[560px]"
                accessibleTitle={t('searchHistory.title')}
            >
                <SheetHeader className="p-0 gap-6 md:pb-6">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-x-3">
                            <SheetClose className="md:hidden cursor-pointer">
                                <Icon
                                    name="close"
                                    className="fill-grey-2 dark:fill-grey"
                                />
                            </SheetClose>
                            <p className="text-2xl font-semibold">
                                {t('searchHistory.title')}
                            </p>
                        </div>
                        <div className="hidden md:flex items-center gap-x-4">
                            <SheetClose className="cursor-pointer">
                                <Icon
                                    name="close"
                                    className="fill-grey-2 dark:fill-grey"
                                />
                            </SheetClose>
                        </div>
                    </div>
                    <div className="relative">
                        <Icon
                            name="search"
                            className="absolute left-4 top-3 size-6 fill-black dark:fill-white"
                        />
                        <Input
                            placeholder={t('searchHistory.placeholder')}
                            value={searchTerm}
                            className="pl-[56px]"
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>
                    <Button
                        className="bg-firefly dark:bg-sky-blue w-full h-12 font-semibold !text-sky-blue dark:!text-black rounded-xl"
                        onClick={handleNewChat}
                    >
                        <Icon
                            name="edit"
                            className="fill-sky-blue dark:fill-black size-6"
                        />
                        {t('sidebar.newChat')}
                    </Button>
                </SheetHeader>
                <div
                    ref={scrollContainerRef}
                    className="space-y-6 dark:text-white overflow-auto pb-12"
                >
                    {Object.entries(groupedSessions)
                        ?.filter(([key, value]) => {
                            return key && value.length > 0
                        })
                        .map(([key, value]) => (
                            <div key={key}>
                                <p className="text-lg font-semibold">
                                    {key === 'today'
                                        ? t('searchHistory.groups.today')
                                        : key === 'yesterday'
                                            ? t('searchHistory.groups.yesterday')
                                            : key === 'last_7_days'
                                                ? t('searchHistory.groups.last7Days')
                                                : t('searchHistory.groups.last30Days')}
                                </p>
                                <div className="space-y-3 mt-3">
                                    {value.map((session) => (
                                        <Link
                                            key={session.id}
                                            to={
                                                session.agent_type === 'chat'
                                                    ? `/chat?id=${session.id}`
                                                    : `/${session.id}`
                                            }
                                            onClick={() => {
                                                dispatch(setMessages([]))
                                                dispatch(setRunStatus(null))
                                            }}
                                            className={cn(
                                                'flex text-sm md:text-base items-center gap-x-2 line-clamp-1 hover:dark:text-sky-blue'
                                            )}
                                        >
                                            {hasSessionDisplayTitle(session) && (
                                                <SessionTitle session={session} />
                                            )}
                                        </Link>
                                    ))}
                                </div>
                            </div>
                        ))}
                    {loadingMore && (
                        <div className="text-center py-2 text-gray-500">
                            {t('common.loadingMore')}
                        </div>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    )
}

export default SearchHistory
