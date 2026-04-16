import type { IMcpSettings } from '@/typings/settings'

export const hasCodexAuth = (
    setting: IMcpSettings | null | undefined
): boolean => Boolean(setting?.metadata?.has_auth || setting?.metadata?.auth_json)
