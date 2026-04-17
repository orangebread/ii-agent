export const ENABLE_BETA = false

export const DEPLOYMENT_MODE =
    import.meta.env.VITE_DEPLOYMENT_MODE?.toLowerCase() || 'hosted'

export const IS_LOCAL_DEPLOYMENT = DEPLOYMENT_MODE === 'local'
export const SHOW_BILLING_UI = !IS_LOCAL_DEPLOYMENT
