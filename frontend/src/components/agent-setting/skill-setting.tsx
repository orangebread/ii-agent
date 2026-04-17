import { useCallback, useEffect, useState } from 'react'
import clsx from 'clsx'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'

import { Button } from '../ui/button'
import { Icon } from '../ui/icon'
import { Switch } from '../ui/switch'
import { settingsService } from '@/services/settings.service'
import { ISkill } from '@/typings/settings'
import ConnectSkill from './connect-skill'

interface SkillSettingProps {
    className?: string
}

const SkillSetting = ({ className }: SkillSettingProps) => {
    const { t } = useTranslation()
    const [skills, setSkills] = useState<ISkill[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [isOpenConnectSkill, setOpenConnectSkill] = useState(false)

    const fetchSkills = useCallback(async () => {
        try {
            setIsLoading(true)
            const response = await settingsService.getSkills(true)
            setSkills(response.skills)
        } catch (error) {
            console.error('Failed to fetch skills:', error)
            toast.error(t('agentSetting.skillSetting.toasts.loadFailed'))
        } finally {
            setIsLoading(false)
        }
    }, [t])

    useEffect(() => {
        fetchSkills()
    }, [fetchSkills])

    const handleToggle = async (
        skillId: string,
        checked: boolean,
        skill: ISkill
    ) => {
        try {
            await settingsService.toggleSkill(skillId, checked)

            // For built-in skills, the API returns a new override entry with different ID
            // So we need to refresh the entire list
            if (skill.source === 'builtin') {
                await fetchSkills()
            } else {
                setSkills((prev) =>
                    prev.map((s) =>
                        s.id === skillId ? { ...s, is_enabled: checked } : s
                    )
                )
            }
            toast.success(
                checked
                    ? t('agentSetting.skillSetting.toasts.enabled')
                    : t('agentSetting.skillSetting.toasts.disabled')
            )
        } catch (error) {
            console.error('Failed to toggle skill:', error)
            toast.error(t('agentSetting.skillSetting.toasts.updateFailed'))
        }
    }

    const handleDeleteSkill = async (skillId: string, skill: ISkill) => {
        if (skill.source === 'builtin') {
            toast.error(
                t('agentSetting.skillSetting.toasts.builtinDeleteBlocked')
            )
            return
        }

        try {
            await settingsService.deleteSkill(skillId)
            setSkills((prev) => prev.filter((s) => s.id !== skillId))
            toast.success(t('agentSetting.skillSetting.toasts.removed'))
        } catch (error) {
            console.error('Failed to delete skill:', error)
            toast.error(t('agentSetting.skillSetting.toasts.deleteFailed'))
        }
    }

    const getSkillIcon = (skill: ISkill) => {
        // Map skill names to appropriate icons
        const name = skill.name.toLowerCase()

        if (name.includes('pdf')) {
            return 'document-pdf'
        } else if (
            name.includes('xlsx') ||
            name.includes('excel') ||
            name.includes('spreadsheet')
        ) {
            return 'table'
        } else if (
            name.includes('docx') ||
            name.includes('word') ||
            name.includes('document')
        ) {
            return 'document-text'
        } else if (
            name.includes('pptx') ||
            name.includes('presentation') ||
            name.includes('slide')
        ) {
            return 'presentation'
        } else if (name.includes('brand') || name.includes('design')) {
            return 'color-swatch'
        } else if (name.includes('code') || name.includes('dev')) {
            return 'code'
        } else if (name.includes('game')) {
            return 'game'
        } else if (name.includes('building-ui')) {
            return 'mobile'
        } else if (name.includes('data-fetching')) {
            return 'mobile'
        }

        // Default icon for other skills
        return 'ai-magic'
    }

    const builtinSkills = skills.filter((s) => s.source === 'builtin')
    const customSkills = skills.filter((s) => s.source !== 'builtin')

    return (
        <div className={`flex flex-col justify-between h-full ${className}`}>
            <div className="space-y-4 w-full flex-1">
                {/* Built-in Skills Section */}
                <div>
                    <p className="text-lg font-semibold dark:text-white">
                        {t('agentSetting.skillSetting.sections.builtin.title')}
                    </p>
                    <p className="mt-1 dark:text-white/[0.56] text-sm">
                        {t(
                            'agentSetting.skillSetting.sections.builtin.subtitle'
                        )}
                    </p>
                </div>

                {isLoading ? (
                    <div className="flex items-center justify-center py-8">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-sky-blue-2 dark:border-sky-blue"></div>
                    </div>
                ) : (
                    <>
                        {builtinSkills.map((skill) => (
                            <div
                                key={skill.id}
                                className={`flex items-center justify-between rounded-2xl ${
                                    skill.is_enabled
                                        ? 'border-2 border-firefly dark:border-sky-blue-2 bg-sky-blue dark:bg-sky-blue-2/20 p-[14px]'
                                        : 'bg-firefly/10 dark:bg-sky-blue-2/5 p-4'
                                }`}
                            >
                                <div className="flex items-center gap-x-4 flex-1">
                                    <div
                                        className={`${
                                            skill.is_enabled
                                                ? 'bg-firefly dark:bg-sky-blue-2'
                                                : 'bg-firefly/10 dark:bg-white/10'
                                        } rounded-full size-[46px] flex items-center justify-center`}
                                    >
                                        <Icon
                                            name={getSkillIcon(skill)}
                                            className={clsx('size-7', {
                                                'fill-sky-blue-2 dark:fill-black':
                                                    skill.is_enabled,
                                                'fill-black dark:fill-white':
                                                    !skill.is_enabled
                                            })}
                                        />
                                    </div>
                                    <div className="flex-1">
                                        <p className="text-base font-semibold dark:text-white capitalize">
                                            {skill.name}
                                        </p>
                                        <p className="mt-1 dark:text-white/80 text-sm line-clamp-2">
                                            {skill.description}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-x-3">
                                    <span className="text-xs text-cha bg-mist text-black px-2 py-1 rounded">
                                        {t(
                                            'agentSetting.skillSetting.badges.builtin'
                                        )}
                                    </span>
                                    <Switch
                                        checked={skill.is_enabled}
                                        onCheckedChange={(checked: boolean) => {
                                            handleToggle(
                                                skill.id,
                                                checked,
                                                skill
                                            )
                                        }}
                                    />
                                </div>
                            </div>
                        ))}

                        {/* Custom Skills Section */}
                        {customSkills.length > 0 && (
                            <>
                                <div className="mt-8">
                                    <p className="text-lg font-semibold dark:text-white">
                                        {t(
                                            'agentSetting.skillSetting.sections.custom.title'
                                        )}
                                    </p>
                                    <p className="mt-1 dark:text-white/[0.56] text-sm">
                                        {t(
                                            'agentSetting.skillSetting.sections.custom.subtitle'
                                        )}
                                    </p>
                                </div>
                                {customSkills.map((skill) => (
                                    <div
                                        key={skill.id}
                                        className={`flex items-center justify-between rounded-2xl ${
                                            skill.is_enabled
                                                ? 'border-2 border-firefly dark:border-sky-blue-2 bg-sky-blue dark:bg-sky-blue-2/20 p-[14px]'
                                                : 'bg-firefly/10 dark:bg-sky-blue-2/5 p-4'
                                        }`}
                                    >
                                        <div className="flex items-center gap-x-4 flex-1">
                                            <div
                                                className={`${
                                                    skill.is_enabled
                                                        ? 'bg-firefly dark:bg-sky-blue-2'
                                                        : 'bg-firefly/10 dark:bg-white/10'
                                                } rounded-full size-[46px] flex items-center justify-center`}
                                            >
                                                <Icon
                                                    name={getSkillIcon(skill)}
                                                    className={clsx('size-7', {
                                                        'fill-sky-blue-2 dark:fill-black':
                                                            skill.is_enabled,
                                                        'fill-black dark:fill-white':
                                                            !skill.is_enabled
                                                    })}
                                                />
                                            </div>
                                            <div className="flex-1">
                                                <p className="text-base font-semibold dark:text-white capitalize">
                                                    {skill.name}
                                                </p>
                                                <p className="mt-1 dark:text-white/80 text-sm line-clamp-2">
                                                    {skill.description}
                                                </p>
                                                {skill.source_url && (
                                                    <a
                                                        href={skill.source_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="text-xs text-sky-blue-2 dark:text-sky-blue hover:underline mt-1 inline-block"
                                                    >
                                                        {t(
                                                            'agentSetting.skillSetting.links.viewOnGithub'
                                                        )}
                                                    </a>
                                                )}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-x-3">
                                            <Button
                                                className="p-0 size-6"
                                                variant="ghost"
                                                onClick={() =>
                                                    handleDeleteSkill(
                                                        skill.id,
                                                        skill
                                                    )
                                                }
                                            >
                                                <Icon
                                                    name="trash"
                                                    className="size-6"
                                                />
                                            </Button>
                                            <Switch
                                                checked={skill.is_enabled}
                                                onCheckedChange={(
                                                    checked: boolean
                                                ) => {
                                                    handleToggle(
                                                        skill.id,
                                                        checked,
                                                        skill
                                                    )
                                                }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </>
                        )}

                        {/* Empty state for custom skills */}
                        {customSkills.length === 0 && (
                            <div className="mt-8 py-8 text-center border-2 border-dashed border-firefly/20 dark:border-white/20 rounded-2xl">
                                <Icon
                                    name="ai-magic"
                                    className="size-12 mx-auto mb-4 fill-firefly/30 dark:fill-white/30"
                                />
                                <p className="text-firefly/60 dark:text-white/60 text-sm">
                                    {t('agentSetting.skillSetting.empty.title')}
                                </p>
                                <p className="text-firefly/40 dark:text-white/40 text-xs mt-1">
                                    {t(
                                        'agentSetting.skillSetting.empty.description',
                                        {
                                            action: t(
                                                'agentSetting.skillSetting.actions.connect'
                                            )
                                        }
                                    )}
                                </p>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Connect Skills Button */}
            <div className="w-full pb-4">
                <Button
                    className="h-12 w-full bg-firefly dark:bg-sky-blue text-sky-blue-2 dark:text-black text-base gap-x-[6px] rounded-xl mt-6"
                    onClick={() => setOpenConnectSkill(true)}
                >
                    <Icon
                        name="link-2"
                        className="fill-sky-blue-2 dark:fill-black size-[22px]"
                    />
                    {t('agentSetting.skillSetting.actions.connect')}
                </Button>
            </div>

            <ConnectSkill
                open={isOpenConnectSkill}
                onOpenChange={(open) => {
                    setOpenConnectSkill(open)
                    if (!open) {
                        fetchSkills()
                    }
                }}
            />
        </div>
    )
}

export default SkillSetting
