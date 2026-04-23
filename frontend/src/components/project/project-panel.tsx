import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'

import { Skeleton } from '@/components/ui/skeleton'
import { projectService } from '@/services/project.service'
import {
    ProjectDatabaseRecordsResponse,
    ProjectDetails,
    ProjectSecretsResponse
} from '@/typings/project'
import ProjectHeader, { ProjectTab } from './project-header'
import ProjectDatabase from './project-database'
import ProjectDeployment from './project-deployment'
import ProjectIntegrations from './project-integrations'
import ProjectSecret from './project-secret'
import ProjectTerminal from './project-terminal'
import { CodeExplorer } from '@/components/agent/code-explorer'
import { setPublished, useAppDispatch } from '@/state'

const RECORD_PAGE_SIZE = 10

interface ProjectPanelProps {
    sessionId?: string
    projectId?: string | null
    agentType?: string
    visible: boolean
    className?: string
}

interface SecretEntry {
    key: string
    value: string
    updatedAt?: string
}

const EMPTY_SECRETS: SecretEntry[] = []

const ProjectPanel = ({
    sessionId,
    projectId,
    agentType,
    visible,
    className
}: ProjectPanelProps) => {
    const { t } = useTranslation()
    const dispatch = useAppDispatch()
    const [activeTab, setActiveTab] = useState<ProjectTab>('code')
    const [project, setProject] = useState<ProjectDetails | null>(null)
    const [isLoadingProject, setIsLoadingProject] = useState(false)

    const [tables, setTables] = useState<string[] | null>(null)
    const [selectedTable, setSelectedTable] = useState<string>('')
    const selectedTableRef = useRef<string>('')
    const [isLoadingTables, setIsLoadingTables] = useState(false)
    const [records, setRecords] =
        useState<ProjectDatabaseRecordsResponse | null>(null)
    const [isLoadingRecords, setIsLoadingRecords] = useState(false)
    const [recordsPageOffset, setRecordsPageOffset] = useState(0)

    const [secretsEntries, setSecretsEntries] =
        useState<SecretEntry[]>(EMPTY_SECRETS)
    const [isSavingSecrets, setIsSavingSecrets] = useState(false)
    const [isLoadingSecrets, setIsLoadingSecrets] = useState(false)

    const resetState = useCallback(() => {
        setActiveTab('code')
        setProject(null)
        setTables(null)
        setSelectedTable('')
        selectedTableRef.current = ''
        setRecords(null)
        setRecordsPageOffset(0)
        setSecretsEntries(EMPTY_SECRETS)
    }, [])

    const fetchProject = useCallback(async () => {
        if (!sessionId || !visible) {
            return
        }
        try {
            setIsLoadingProject(true)
            const data = await projectService.getSessionProject(sessionId)
            setProject(data)
            dispatch(setPublished(data?.production_url || null))
        } catch (error) {
            console.error('Failed to fetch project details', error)
            toast.error(t('project.panel.errors.unableToLoadProject'))
        } finally {
            setIsLoadingProject(false)
        }
    }, [dispatch, sessionId, t, visible])

    const fetchSecrets = useCallback(async () => {
        if (!sessionId || !visible) {
            return
        }
        try {
            setIsLoadingSecrets(true)
            const response: ProjectSecretsResponse =
                await projectService.getProjectSecrets(sessionId)
            const entries = Object.entries(response.secrets || {}).map(
                ([key, value]) => ({
                    key,
                    value:
                        typeof value === 'string'
                            ? value
                            : JSON.stringify(value, null, 2),
                    updatedAt: response.updated_at ?? undefined
                })
            )
            setSecretsEntries(entries.length > 0 ? entries : [])
        } catch (error) {
            console.error('Failed to fetch secrets', error)
            setSecretsEntries([])
        } finally {
            setIsLoadingSecrets(false)
        }
    }, [sessionId, visible])

    const resolvedProjectId = useMemo(
        () => projectId ?? project?.id ?? null,
        [projectId, project?.id]
    )

    const hasDatabaseConfig = useMemo(() => {
        if (!project?.database) {
            return false
        }
        return Object.keys(project.database).length > 0
    }, [project?.database])

    const fetchSchema = useCallback(async () => {
        const targetProjectId = resolvedProjectId
        if (!targetProjectId || !visible || !hasDatabaseConfig) {
            setTables(null)
            setSelectedTable('')
            selectedTableRef.current = ''
            setRecords(null)
            setRecordsPageOffset(0)
            return
        }
        try {
            setIsLoadingTables(true)
            const response =
                await projectService.getProjectDatabaseSchema(targetProjectId)
            const tableNames = response.tables
            setTables(tableNames)
            const currentSelectedTable = selectedTableRef.current
            if (tableNames.length > 0) {
                if (
                    !currentSelectedTable ||
                    !tableNames.includes(currentSelectedTable)
                ) {
                    setSelectedTable(tableNames[0])
                    selectedTableRef.current = tableNames[0]
                    setRecordsPageOffset(0)
                    setRecords(null)
                }
            } else {
                setSelectedTable('')
                selectedTableRef.current = ''
                setRecords(null)
                setRecordsPageOffset(0)
            }
        } catch (error) {
            console.error('Failed to load database schema', error)
            toast.error(t('project.panel.errors.unableToLoadSchema'))
            setTables(null)
            setSelectedTable('')
            selectedTableRef.current = ''
        } finally {
            setIsLoadingTables(false)
        }
    }, [hasDatabaseConfig, resolvedProjectId, t, visible])

    const fetchRecords = useCallback(
        async (table: string, offset = 0) => {
            const targetProjectId = resolvedProjectId
            if (!targetProjectId || !table || !visible || !hasDatabaseConfig) {
                return
            }
            try {
                setIsLoadingRecords(true)
                const response = await projectService.getProjectDatabaseRecords(
                    targetProjectId,
                    { table, limit: RECORD_PAGE_SIZE, offset }
                )
                setRecords(response)
                setRecordsPageOffset(response.offset)
            } catch (error) {
                console.error('Failed to load table records', error)
                toast.error(t('project.panel.errors.unableToLoadRecords'))
            } finally {
                setIsLoadingRecords(false)
            }
        },
        [hasDatabaseConfig, resolvedProjectId, t, visible]
    )

    useEffect(() => {
        if (visible) {
            fetchProject()
            fetchSecrets()
        }
    }, [visible, fetchProject, fetchSecrets])

    useEffect(() => {
        if (visible && activeTab === 'database' && tables === null) {
            fetchSchema()
        }
    }, [visible, activeTab, fetchSchema, tables])

    useEffect(() => {
        if (
            visible &&
            activeTab === 'database' &&
            selectedTable &&
            hasDatabaseConfig
        ) {
            fetchRecords(selectedTable, recordsPageOffset)
        }
    }, [
        visible,
        activeTab,
        selectedTable,
        fetchRecords,
        hasDatabaseConfig,
        recordsPageOffset
    ])

    useEffect(() => {
        if (!visible) {
            resetState()
        }
    }, [visible, resetState])

    const handleSelectTable = (table: string) => {
        if (table === selectedTable) {
            return
        }
        setSelectedTable(table)
        selectedTableRef.current = table
        setRecords(null)
        setRecordsPageOffset(0)
        setIsLoadingRecords(true)
    }

    const handleRefreshRecords = () => {
        if (selectedTable) {
            fetchRecords(selectedTable, recordsPageOffset)
        }
    }

    const handleNextPage = () => {
        if (!selectedTable) {
            return
        }
        const nextOffset = recordsPageOffset + RECORD_PAGE_SIZE
        setIsLoadingRecords(true)
        setRecordsPageOffset(nextOffset)
    }

    const handlePrevPage = () => {
        if (!selectedTable || recordsPageOffset === 0) {
            return
        }
        setIsLoadingRecords(true)
        setRecordsPageOffset((prev) => Math.max(0, prev - RECORD_PAGE_SIZE))
    }

    const handleAddSecret = async (
        secrets: Array<{ key: string; value: string }>
    ) => {
        if (!sessionId) {
            toast.error(t('project.panel.errors.missingSession'))
            return
        }
        const payload = secrets.reduce<Record<string, string>>(
            (acc, entry) => {
                const k = entry.key.trim()
                if (k) {
                    acc[k] = entry.value
                }
                return acc
            },
            {}
        )

        try {
            setIsSavingSecrets(true)
            const response = await projectService.addProjectSecrets(
                sessionId,
                payload
            )
            toast.success(
                t('project.secrets.toasts.added', { count: secrets.length })
            )
            maybeNotifyRestartRequired(response.restart_required)
            await fetchSecrets()
        } catch (error) {
            console.error('Failed to add secret', error)
            toast.error(t('project.secrets.errors.unableToAdd'))
        } finally {
            setIsSavingSecrets(false)
        }
    }

    const maybeNotifyRestartRequired = (restartRequired?: boolean) => {
        if (!restartRequired) {
            return
        }

        toast.info(
            'Existing terminals and development servers may need to be restarted ' +
                'to pick up updated environment variables.'
        )
    }

    const handleSecretChange = (
        index: number,
        field: keyof SecretEntry,
        value: string
    ) => {
        setSecretsEntries((prev) =>
            prev.map((entry, idx) =>
                idx === index
                    ? {
                          ...entry,
                          [field]: value
                      }
                    : entry
            )
        )
    }

    const handleEditSecret = async (
        index: number,
        key: string,
        value: string
    ) => {
        if (!sessionId) {
            toast.error(t('project.panel.errors.missingSession'))
            return
        }
        // Build updated entries with the edited values
        const updatedEntries = secretsEntries.map((entry, idx) =>
            idx === index ? { ...entry, key, value } : entry
        )
        const payload = updatedEntries.reduce<Record<string, string>>(
            (acc, entry) => {
                const k = entry.key.trim()
                if (k) {
                    acc[k] = entry.value
                }
                return acc
            },
            {}
        )
        try {
            setIsSavingSecrets(true)
            const response = await projectService.replaceProjectSecrets(
                sessionId,
                payload
            )
            toast.success(t('project.secrets.toasts.updated'))
            maybeNotifyRestartRequired(response.restart_required)
            await fetchSecrets()
        } catch (error) {
            console.error('Failed to edit secret', error)
            toast.error(t('project.secrets.errors.unableToUpdate'))
        } finally {
            setIsSavingSecrets(false)
        }
    }

    const handleRemoveSecret = async (index: number) => {
        if (!sessionId) {
            toast.error(t('project.panel.errors.missingSession'))
            return
        }
        const secretKey = secretsEntries[index]?.key?.trim()
        if (!secretKey) {
            toast.error(t('project.secrets.errors.unableToDelete'))
            return
        }
        try {
            setIsSavingSecrets(true)
            const response = await projectService.deleteProjectSecrets(
                sessionId,
                [secretKey]
            )
            toast.success(t('project.secrets.toasts.deleted'))
            maybeNotifyRestartRequired(response.restart_required)
            await fetchSecrets()
        } catch (error) {
            console.error('Failed to delete secret', error)
            toast.error(t('project.secrets.errors.unableToDelete'))
        } finally {
            setIsSavingSecrets(false)
        }
    }

    const handleSaveSecrets = async () => {
        if (!sessionId) {
            toast.error(t('project.panel.errors.missingSession'))
            return
        }

        const payload = secretsEntries.reduce<Record<string, string>>(
            (acc, entry) => {
                const key = entry.key.trim()
                if (key) {
                    acc[key] = entry.value
                }
                return acc
            },
            {}
        )

        try {
            setIsSavingSecrets(true)
            const response = await projectService.replaceProjectSecrets(
                sessionId,
                payload
            )
            toast.success(t('project.secrets.toasts.updated'))
            maybeNotifyRestartRequired(response.restart_required)
            await fetchSecrets()
        } catch (error) {
            console.error('Failed to update secrets', error)
            toast.error(t('project.secrets.errors.unableToUpdate'))
        } finally {
            setIsSavingSecrets(false)
        }
    }

    const recordColumns = useMemo(() => {
        if (!records || records.rows.length === 0) {
            return []
        }
        const firstRow = records.rows[0]
        return Object.keys(firstRow)
    }, [records])

    const renderContent = () => {
        if (!sessionId) {
            return (
                <p className="text-sm text-muted-foreground">
                    {t('project.panel.sessionRequired')}
                </p>
            )
        }

        if (isLoadingProject && !project) {
            return (
                <div className="space-y-2">
                    <Skeleton className="h-6 w-48" />
                    <Skeleton className="h-40 w-full" />
                </div>
            )
        }

        if (!project) {
            return (
                <p className="text-sm text-muted-foreground">
                    {t('project.panel.noProjectYet')}
                </p>
            )
        }

        switch (activeTab) {
            case 'code':
                return (
                    <CodeExplorer className="h-[calc(100vh-280px)] overflow-hidden rounded-lg border border-border bg-background" />
                )
            case 'terminal':
                return <ProjectTerminal sessionId={sessionId} />
            case 'database':
                return (
                    <div className="relative">
                        {isLoadingTables && (
                            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 backdrop-blur-sm">
                                <div className="flex flex-col items-center gap-3">
                                    <div className="h-8 w-8 animate-spin rounded-full border-4 border-firefly dark:border-sky-blue border-t-transparent" />
                                    <p className="text-sm text-muted-foreground">
                                        {t('project.panel.loadingSchema')}
                                    </p>
                                </div>
                            </div>
                        )}
                        <ProjectDatabase
                            resolvedProjectId={resolvedProjectId}
                            hasDatabaseConfig={hasDatabaseConfig}
                            isLoadingTables={isLoadingTables}
                            tables={tables ?? []}
                            selectedTable={selectedTable}
                            records={records}
                            isLoadingRecords={isLoadingRecords}
                            recordsPageOffset={recordsPageOffset}
                            recordColumns={recordColumns}
                            onSelectTable={handleSelectTable}
                            onRefreshSchema={fetchSchema}
                            onRefreshRecords={handleRefreshRecords}
                            onNextPage={handleNextPage}
                            onPrevPage={handlePrevPage}
                        />
                    </div>
                )
            case 'domain':
                return <ProjectDeployment />
            case 'integrations':
                return <ProjectIntegrations agentType={agentType} />
            case 'secrets':
            default:
                return (
                    <ProjectSecret
                        secretsEntries={secretsEntries}
                        isLoadingSecrets={isLoadingSecrets}
                        isSavingSecrets={isSavingSecrets}
                        onAddSecret={handleAddSecret}
                        onSecretChange={handleSecretChange}
                        onEditSecret={handleEditSecret}
                        onRemoveSecret={handleRemoveSecret}
                        onSaveSecrets={handleSaveSecrets}
                        onResetSecrets={fetchSecrets}
                    />
                )
        }
    }

    if (!visible) {
        return null
    }

    return (
        <section className={clsx('relative overflow-hidden', className)}>
            <ProjectHeader activeTab={activeTab} onTabChange={setActiveTab} />
            <div className="relative z-10 flex flex-col gap-4 py-4 md:py-6">
                <div className="min-h-[320px]">{renderContent()}</div>
            </div>
        </section>
    )
}

export default ProjectPanel
