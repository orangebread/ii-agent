import { useMemo, useState } from 'react'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { useNavigate, useParams } from 'react-router'
import { useTranslation } from 'react-i18next'

dayjs.extend(utc)

import { cn } from '@/lib/utils'
import { useGetSessionUsageDetailQuery } from '@/state'
import {
    Table,
    TableBody,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow
} from './ui/table'
import { Icon } from './ui/icon'
import { Checkbox } from './ui/checkbox'
import { IS_LOCAL_DEPLOYMENT } from '@/constants/features'

const formatCredit = (value: number) =>
    value.toLocaleString('en-US', {
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
    })

const formatTokens = (value: number) =>
    value > 0 ? value.toLocaleString('en-US') : '-'

const formatUsd = (value: number | null | undefined) =>
    value != null
        ? value.toLocaleString('en-US', {
              style: 'currency',
              currency: 'USD',
              minimumFractionDigits: 4,
              maximumFractionDigits: 4
          })
        : '-'

const getBillingLabel = (item: {
    billing_kind: string
    model_id: string | null
    tool_name: string | null
}) => {
    if (item.tool_name) {
        return item.tool_name
    }
    if (item.model_id) {
        return item.model_id
    }
    return item.billing_kind
}

const getBillingType = (item: {
    billing_kind: string
    tool_name: string | null
}) => {
    if (item.tool_name || item.billing_kind === 'tool_usage') {
        return 'Tool'
    }
    return 'LLM'
}

const SessionUsageDetail = () => {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { sessionId } = useParams<{ sessionId: string }>()
    const [hideZeroCost, setHideZeroCost] = useState(false)

    const { data, isLoading } = useGetSessionUsageDetailQuery(
        { sessionId: sessionId! },
        { skip: !sessionId }
    )

    const filteredItems = useMemo(() => {
        if (!data?.items) return []
        if (!hideZeroCost) return data.items
        return data.items.filter((item) => item.credits_charged !== 0)
    }, [data?.items, hideZeroCost])

    const totalUsd = useMemo(() => {
        if (!data?.items?.length) return null

        const values = data.items
            .map((item) => item.cost_usd)
            .filter((value): value is number => value != null)

        if (!values.length) return null

        return values.reduce((sum, value) => sum + value, 0)
    }, [data?.items])

    const handleBack = () => {
        navigate('/settings')
    }

    return (
        <div className="p-3 md:p-0 min-h-screen bg-background">
            <div className="max-w-3xl mx-auto md:pb-8 md:pt-16">
                <div className="flex items-center gap-x-3 md:gap-x-4 mb-6">
                    <button className="cursor-pointer" onClick={handleBack}>
                        <Icon
                            name="arrow-left"
                            className="size-8 hidden dark:inline"
                        />
                        <Icon
                            name="arrow-left-dark"
                            className="size-8 inline dark:hidden"
                        />
                    </button>
                    <div className="flex flex-col">
                        <span className="text-black dark:text-sky-blue text-2xl md:text-[32px] font-semibold">
                            {t('settings.tabs.usage')}
                        </span>
                        {data?.session_title && (
                            <span className="text-sm text-black/60 dark:text-white/60 line-clamp-1 mt-1">
                                {data.session_title}
                            </span>
                        )}
                    </div>
                </div>

                <div className="flex items-center gap-2 mb-3">
                    <Checkbox
                        id="hide-zero-usage"
                        checked={hideZeroCost}
                        onCheckedChange={(v) => setHideZeroCost(v === true)}
                    />
                    <label
                        htmlFor="hide-zero-usage"
                        className="text-xs text-black/60 dark:text-white/60 cursor-pointer select-none"
                    >
                        Hide zero-cost entries
                    </label>
                </div>

                <div className="rounded-2xl overflow-x-hidden">
                    <div className="p-0">
                        <Table>
                            <TableHeader className="hidden md:table-header-group overflow-hidden">
                                <TableRow>
                                    <TableHead className="py-4 text-lg w-[10%]">
                                        Type
                                    </TableHead>
                                    <TableHead className="py-4 text-lg w-[30%]">
                                        Description
                                    </TableHead>
                                    <TableHead className="py-4 text-lg text-right w-[15%]">
                                        Input
                                    </TableHead>
                                    <TableHead className="py-4 text-lg text-right w-[15%]">
                                        Output
                                    </TableHead>
                                    <TableHead className="py-4 text-lg text-right w-[15%]">
                                        {t('credit.table.date')}
                                    </TableHead>
                                    <TableHead className="py-4 text-lg text-right w-[15%]">
                                        {IS_LOCAL_DEPLOYMENT
                                            ? 'Estimated cost'
                                            : 'Credits'}
                                    </TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {isLoading && (
                                    <TableRow>
                                        <TableCell
                                            className="py-6 pl-6"
                                            colSpan={6}
                                        >
                                            {t('common.loading')}
                                        </TableCell>
                                    </TableRow>
                                )}
                                {!isLoading && filteredItems.length === 0 && (
                                    <TableRow>
                                        <TableCell
                                            className="py-6 pl-6"
                                            colSpan={6}
                                        >
                                            {t('credit.noRecords')}
                                        </TableCell>
                                    </TableRow>
                                )}

                                {!isLoading &&
                                    filteredItems.map((item) => {
                                        const type = getBillingType(item)
                                        return (
                                            <TableRow
                                                key={item.id}
                                                className="border-0"
                                            >
                                                <TableCell className="pt-4 text-sm w-[10%]">
                                                    <span
                                                        className={cn(
                                                            'inline-block px-2 py-0.5 rounded-full text-xs font-medium',
                                                            type === 'LLM'
                                                                ? 'bg-sky-blue/20 text-firefly dark:bg-sky-blue/30 dark:text-sky-blue'
                                                                : 'bg-yellow/20 text-firefly dark:bg-yellow/30 dark:text-yellow'
                                                        )}
                                                    >
                                                        {type}
                                                    </span>
                                                </TableCell>
                                                <TableCell className="pt-4 pr-4 text-sm w-[30%] whitespace-normal">
                                                    <span className="line-clamp-1">
                                                        {getBillingLabel(item)}
                                                    </span>
                                                    {item.provider && (
                                                        <span className="text-xs text-black/40 dark:text-white/40 block">
                                                            {item.provider}
                                                        </span>
                                                    )}
                                                </TableCell>
                                                <TableCell className="pt-4 text-sm text-right w-[15%] tabular-nums">
                                                    {formatTokens(
                                                        item.input_tokens
                                                    )}
                                                </TableCell>
                                                <TableCell className="pt-4 text-sm text-right w-[15%] tabular-nums">
                                                    {formatTokens(
                                                        item.output_tokens
                                                    )}
                                                </TableCell>
                                                <TableCell className="pt-4 text-sm text-right w-[15%]">
                                                    {dayjs
                                                        .utc(item.created_at)
                                                        .local()
                                                        .format(
                                                            'DD MMM, HH:mm'
                                                        )}
                                                </TableCell>
                                                <TableCell className="pt-4 text-sm text-right w-[15%] tabular-nums">
                                                    {IS_LOCAL_DEPLOYMENT
                                                        ? formatUsd(
                                                              item.cost_usd
                                                          )
                                                        : formatCredit(
                                                              item.credits_charged
                                                          )}
                                                </TableCell>
                                            </TableRow>
                                        )
                                    })}
                            </TableBody>
                            {!isLoading &&
                                data?.items &&
                                data.items.length > 0 && (
                                    <TableFooter>
                                        <TableRow className="border-t border-black/10 dark:border-white/10">
                                            <TableCell
                                                colSpan={5}
                                                className="py-4 text-sm font-semibold"
                                            >
                                                Total ({data.total_items}{' '}
                                                {data.total_items === 1
                                                    ? 'item'
                                                    : 'items'}
                                                )
                                            </TableCell>
                                            <TableCell className="py-4 text-sm text-right font-semibold tabular-nums">
                                                {IS_LOCAL_DEPLOYMENT
                                                    ? formatUsd(totalUsd)
                                                    : formatCredit(
                                                          data.total_credits
                                                      )}
                                            </TableCell>
                                        </TableRow>
                                    </TableFooter>
                                )}
                        </Table>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default SessionUsageDetail
