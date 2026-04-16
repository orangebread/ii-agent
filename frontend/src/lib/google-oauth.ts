export const getGoogleOAuthClientId = (): string =>
    import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim() || ''

export const isGoogleOAuthConfigured = (): boolean =>
    getGoogleOAuthClientId().length > 0
