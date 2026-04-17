import { useMemo, useState } from 'react'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

dayjs.extend(utc)

import { cn } from '@/lib/utils'
import { useGetCreditBalanceQuery, useGetCreditUsageQuery } from '@/state'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from './ui/table'
import CreditTooltip from './credit-tooltip'
import { Icon } from './ui/icon'
import { IS_LOCAL_DEPLOYMENT } from '@/constants/features'

interface CreditUsageProps {
    className?: string
    perPage?: number
}

const CreditUsage = ({ className, perPage = 20 }: CreditUsageProps) => {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [page, setPage] = useState(1)

    // Use RTK Query hooks instead of Redux dispatch and selectors
    const { data: balanceData } = useGetCreditBalanceQuery(undefined, {
        skip: IS_LOCAL_DEPLOYMENT
    })
    const { data: usage, isLoading: loading } = useGetCreditUsageQuery({
        page,
        perPage
    })

    const availableCredit = balanceData?.credits || 0
    const bonusCredit = balanceData?.bonus_credits || 0

    const totalPages = useMemo(() => {
        if (!usage?.total) return 1
        return Math.max(1, Math.ceil(usage.total / perPage))
    }, [usage?.total, perPage])

    const totalCredit = useMemo(() => {
        return availableCredit + bonusCredit
    }, [availableCredit, bonusCredit])

    const goPrev = () => setPage((p) => Math.max(1, p - 1))
    const goNext = () => setPage((p) => Math.min(totalPages, p + 1))
    const goTo = (p: number) =>
        setPage(() => Math.min(totalPages, Math.max(1, p)))

    const formatCreditBalance = (value: number) => {
        const rounded = Math.round(value)
        return (rounded === 0 ? 0 : rounded).toLocaleString('en-US')
    }

    const formatCredit = (value: number) =>
        value.toLocaleString('en-US', {
            minimumFractionDigits: 4,
            maximumFractionDigits: 4
        })

    return (
        <div className={cn('rounded-2xl overflow-x-hidden', className)}>
            {!IS_LOCAL_DEPLOYMENT && (
                <div className="flex mb-2">
                    <CreditTooltip
                        credits={availableCredit}
                        bonusCredits={bonusCredit}
                        hideViewUsage
                    >
                        <div className="text-xs font-semibold text-black bg-yellow px-4 py-1 rounded-4xl flex items-center gap-x-[6px] cursor-default">
                            <Icon name="coin" className="fill-firefly" />
                            <p>{formatCreditBalance(totalCredit)}</p>
                        </div>
                    </CreditTooltip>
                </div>
            )}
            <div className="p-0">
                <Table>
                    <TableHeader className="hidden md:table-header-group overflow-hidden">
                        <TableRow>
                            <TableHead className="py-4 text-lg w-[60%]">
                                {t('credit.table.chat')}
                            </TableHead>
                            <TableHead className="py-4 text-lg w-[25%]">
                                {t('credit.table.date')}
                            </TableHead>
                            {!IS_LOCAL_DEPLOYMENT && (
                                <TableHead className="py-4 text-lg text-right w-[15%]">
                                    {t('credit.table.creditsChange')}
                                </TableHead>
                            )}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && (
                            <TableRow>
                                <TableCell
                                    className="py-6 pl-6"
                                    colSpan={IS_LOCAL_DEPLOYMENT ? 2 : 3}
                                >
                                    {t('common.loading')}
                                </TableCell>
                            </TableRow>
                        )}
                        {!loading && usage?.sessions?.length === 0 && (
                            <TableRow>
                                <TableCell
                                    className="py-6 pl-6"
                                    colSpan={IS_LOCAL_DEPLOYMENT ? 2 : 3}
                                >
                                    {t('credit.noRecords')}
                                </TableCell>
                            </TableRow>
                        )}

                        {!loading &&
                            usage?.sessions?.map((s) => (
                                <TableRow
                                    key={s.session_id}
                                    className="border-0 cursor-pointer hover:!bg-transparent opacity-75 hover:opacity-100 transition-opacity"
                                    onClick={() =>
                                        navigate(
                                            `/settings/usage/${s.session_id}`
                                        )
                                    }
                                >
                                    <TableCell className="pt-4 pr-4 text-sm w-[60%] whitespace-normal">
                                        <span className="line-clamp-1">
                                            {s.session_title}
                                        </span>
                                    </TableCell>
                                    <TableCell className="pt-4 text-sm w-[25%]">
                                        <span className="hidden">
                                            {dayjs
                                                .utc(s.updated_at)
                                                .local()
                                                .format('DD MMM YYYY, hh:mm A')}
                                        </span>
                                        <span className="inline">
                                            {dayjs
                                                .utc(s.updated_at)
                                                .local()
                                                .format('DD MMM YYYY')}
                                        </span>
                                    </TableCell>
                                    {!IS_LOCAL_DEPLOYMENT && (
                                        <TableCell
                                            className={cn(
                                                'pt-4 text-right text-sm w-[15%]'
                                            )}
                                        >
                                            {s.credits > 0
                                                ? `+${formatCredit(s.credits)}`
                                                : formatCredit(s.credits)}
                                        </TableCell>
                                    )}
                                </TableRow>
                            ))}
                    </TableBody>
                </Table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-center gap-2 py-4 select-none">
                <button
                    type="button"
                    onClick={goPrev}
                    disabled={page === 1}
                    className={cn(
                        'flex items-center gap-1 px-2 py-1 text-sm text-black dark:text-white cursor-pointer',
                        page === 1 && 'opacity-50 cursor-not-allowed'
                    )}
                >
                    <Icon
                        name="arrow-left-2"
                        className="size-4 fill-black/40 dark:fill-white/40"
                    />
                    {t('common.previous')}
                </button>

                {/* Simple page indicators: current, next */}
                <button
                    type="button"
                    onClick={() => goTo(page)}
                    className={cn(
                        'px-2 py-1 text-sm rounded-md',
                        'text-black dark:text-white',
                        'font-medium'
                    )}
                >
                    {page}
                </button>
                {page < totalPages && (
                    <button
                        type="button"
                        onClick={() => goTo(page + 1)}
                        className={cn(
                            'px-2 py-1 text-sm text-black/60 dark:text-white/60'
                        )}
                    >
                        {page + 1}
                    </button>
                )}

                <button
                    type="button"
                    onClick={goNext}
                    disabled={page === totalPages}
                    className={cn(
                        'flex items-center gap-1 px-2 py-1 text-sm text-black dark:text-white cursor-pointer',
                        page === totalPages && 'opacity-50 cursor-not-allowed'
                    )}
                >
                    {t('common.next')}
                    <Icon
                        name="arrow-right-2"
                        className="size-4 fill-black/40 dark:fill-white/40"
                    />
                </button>
            </div>
        </div>
    )
}

export default CreditUsage
