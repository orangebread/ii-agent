export type ProjectDetails = {
    id: string
    user_id: string
    session_id: string | null
    name?: string | null
    project_name?: string | null
    description?: string | null
    status?: string
    current_build_status?: string
    framework?: string | null
    project_path?: string | null
    production_url?: string | null
    database?: Record<string, unknown> | null
    storage?: Record<string, unknown> | null
    secrets?: Record<string, unknown> | null
    current_production_deployment_id?: string | null
    created_at?: string | null
    updated_at?: string | null
}

export type ProjectSecretsResponse = {
    project_id: string
    session_id: string
    secrets: Record<string, unknown>
    restart_required?: boolean
    updated_at?: string | null
}

export type ProjectDatabaseSchemaResponse = {
    project_id: string
    tables: string[]
}

export type ProjectDatabaseRecordsResponse = {
    project_id: string
    table: string
    limit: number
    offset: number
    total: number
    rows: Record<string, unknown>[]
}

export type ProjectDeploymentResponse = {
    id?: string | null
    project_id: string
    provider?: string | null
    deployment_url?: string | null
    deployment_status?: string | null
    version?: number | null
    has_deployment: boolean
}
