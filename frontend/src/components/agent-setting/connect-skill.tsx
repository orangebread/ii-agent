import { zodResolver } from '@hookform/resolvers/zod'
import type { TFunction } from 'i18next'
import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { z } from 'zod'

import { settingsService } from '@/services/settings.service'
import { Button } from '../ui/button'
import {
    Form,
    FormControl,
    FormField,
    FormItem,
    FormLabel,
    FormMessage
} from '../ui/form'
import { Icon } from '../ui/icon'
import { Input } from '../ui/input'
import { Sheet, SheetClose, SheetContent, SheetHeader } from '../ui/sheet'
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger
} from '../ui/collapsible'

const getFormSchema = (t: TFunction) =>
    z.object({
        github_url: z
            .string()
            .min(
                1,
                t('agentSetting.skillSetting.connect.validation.urlRequired')
            )
            .regex(
                /^https:\/\/github\.com\/[^/]+\/[^/]+\/tree\/[^/]+\/.+$/,
                t('agentSetting.skillSetting.connect.validation.urlInvalid')
            )
    })

type FormValues = z.infer<ReturnType<typeof getFormSchema>>

interface ConnectSkillProps {
    open: boolean
    onOpenChange: (open: boolean) => void
}

const ConnectSkill = ({ open, onOpenChange }: ConnectSkillProps) => {
    const { t } = useTranslation()
    const [isLoading, setIsLoading] = useState(false)
    const [isGuideOpen, setIsGuideOpen] = useState(false)
    const formSchema = useMemo(() => getFormSchema(t), [t])

    const exampleUrls = t(
        'agentSetting.skillSetting.connect.guide.exampleUrls.items',
        { returnObjects: true }
    ) as Array<{ name: string; url: string }>

    const form = useForm<FormValues>({
        resolver: zodResolver(formSchema),
        defaultValues: {
            github_url: ''
        }
    })

    const onSubmit = async (data: FormValues) => {
        try {
            setIsLoading(true)
            const skill = await settingsService.addSkillFromGitHub(
                data.github_url
            )
            toast.success(
                t('agentSetting.skillSetting.toasts.connected', {
                    name: skill.name
                })
            )
            onOpenChange(false)
            form.reset()
        } catch (error: any) {
            console.error('Failed to connect skill:', error)
            const errorMessage =
                error?.response?.data?.detail ||
                t('agentSetting.skillSetting.toasts.connectFailed')
            toast.error(errorMessage)
        } finally {
            setIsLoading(false)
        }
    }

    const handleCancel = () => {
        onOpenChange(false)
        form.reset()
    }

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                className="px-3 md:px-6 py-3 md:py-12 w-full !max-w-[560px]"
                accessibleTitle={t('agentSetting.skillSetting.connect.title')}
                accessibleDescription={t(
                    'agentSetting.skillSetting.connect.description'
                )}
            >
                <SheetHeader className="p-0 gap-6 pb-4">
                    <div className="flex items-center justify-between">
                        <p className="text-2xl font-semibold dark:text-white">
                            {t('agentSetting.skillSetting.connect.title')}
                        </p>
                        <div className="flex items-center gap-x-4">
                            <SheetClose className="cursor-pointer">
                                <Icon
                                    name="arrow-right"
                                    className="dark:inline hidden"
                                />
                                <Icon
                                    name="arrow-right-dark"
                                    className="dark:hidden inline"
                                />
                            </SheetClose>
                        </div>
                    </div>
                </SheetHeader>
                <div className="mb-4">
                    <p className="text-sm dark:text-white/60 text-firefly/60">
                        {t('agentSetting.skillSetting.connect.description')}
                    </p>
                </div>

                {/* Best Practices Guide */}
                <Collapsible
                    open={isGuideOpen}
                    onOpenChange={setIsGuideOpen}
                    className="mb-6"
                >
                    <CollapsibleTrigger className="flex items-center gap-2 w-full p-3 rounded-xl bg-firefly/10 dark:bg-sky-blue-2/20 hover:bg-firefly/20 dark:hover:bg-sky-blue-2/30 transition-colors">
                        <Icon
                            name="help"
                            className="size-5 fill-firefly dark:fill-sky-blue-2"
                        />
                        <span className="text-sm font-medium text-firefly dark:text-sky-blue-2">
                            {t(
                                'agentSetting.skillSetting.connect.guide.toggle'
                            )}
                        </span>
                        <Icon
                            name={isGuideOpen ? 'arrow-up' : 'arrow-down'}
                            className="size-4 fill-firefly text-firefly dark:fill-sky-blue-2 dark:text-sky-blue-2 ml-auto"
                        />
                    </CollapsibleTrigger>
                    <CollapsibleContent className="mt-3 p-4 rounded-xl bg-white dark:bg-white border border-gray-200">
                        <div className="space-y-4">
                            {/* What are Skills */}
                            <div>
                                <h4 className="font-medium text-sm text-black">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.whatAreSkills.title'
                                    )}
                                </h4>
                                <p className="text-sm text-gray-600 mt-1">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.whatAreSkills.content'
                                    )}
                                </p>
                            </div>

                            {/* Where to Find */}
                            <div>
                                <h4 className="font-medium text-sm text-black">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.whereToFind.title'
                                    )}
                                </h4>
                                <p className="text-sm text-gray-600 mt-1">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.whereToFind.content'
                                    )}
                                </p>
                                <a
                                    href={t(
                                        'agentSetting.skillSetting.connect.guide.whereToFind.url'
                                    )}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline mt-1"
                                >
                                    <Icon
                                        name="link-2"
                                        className="size-3 fill-blue-600"
                                    />
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.whereToFind.link'
                                    )}
                                </a>
                            </div>

                            {/* How to Get URL */}
                            <div>
                                <h4 className="font-medium text-sm text-black">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.howToGetUrl.title'
                                    )}
                                </h4>
                                <div className="text-sm text-gray-600 mt-1 space-y-1">
                                    <p>
                                        {t(
                                            'agentSetting.skillSetting.connect.guide.howToGetUrl.step1'
                                        )}
                                    </p>
                                    <p>
                                        {t(
                                            'agentSetting.skillSetting.connect.guide.howToGetUrl.step2'
                                        )}
                                    </p>
                                    <p>
                                        {t(
                                            'agentSetting.skillSetting.connect.guide.howToGetUrl.step3'
                                        )}
                                    </p>
                                    <p>
                                        {t(
                                            'agentSetting.skillSetting.connect.guide.howToGetUrl.step4'
                                        )}
                                    </p>
                                </div>
                                <p className="text-xs text-amber-600 mt-2 italic">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.howToGetUrl.tip'
                                    )}
                                </p>
                            </div>

                            {/* Example URLs */}
                            <div>
                                <h4 className="font-medium text-sm text-black">
                                    {t(
                                        'agentSetting.skillSetting.connect.guide.exampleUrls.title'
                                    )}
                                </h4>
                                <div className="flex flex-wrap gap-2 mt-2">
                                    {Array.isArray(exampleUrls) &&
                                        exampleUrls.map((example) => (
                                            <a
                                                key={example.name}
                                                href={example.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-xs px-2 py-1 rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                                            >
                                                {example.name}
                                            </a>
                                        ))}
                                </div>
                            </div>
                        </div>
                    </CollapsibleContent>
                </Collapsible>
                <Form {...form}>
                    <form
                        onSubmit={form.handleSubmit(onSubmit)}
                        className="space-y-6 overflow-auto pb-4 md:pb-12"
                    >
                        <FormField
                            control={form.control}
                            name="github_url"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-lg dark:text-white">
                                        {t(
                                            'agentSetting.skillSetting.connect.form.label'
                                        )}
                                    </FormLabel>
                                    <FormControl>
                                        <div className="space-y-2 relative">
                                            <Icon
                                                name="link-2"
                                                className={`absolute top-1/2 -translate-y-1/2 left-4 fill-black dark:fill-white ${field.value ? '' : 'opacity-30'}`}
                                            />
                                            <Input
                                                id="github-url"
                                                className="pl-[56px] h-12"
                                                placeholder={t(
                                                    'agentSetting.skillSetting.connect.form.placeholder'
                                                )}
                                                {...field}
                                            />
                                        </div>
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />

                        <div className="bg-firefly/5 dark:bg-sky-blue-2/10 rounded-xl p-4">
                            <p className="text-sm font-medium dark:text-white mb-2">
                                {t(
                                    'agentSetting.skillSetting.connect.urlFormat.title'
                                )}
                            </p>
                            <code className="text-xs dark:text-white/60 text-firefly/60 break-all">
                                {t(
                                    'agentSetting.skillSetting.connect.urlFormat.format'
                                )}
                            </code>
                            <p className="text-xs dark:text-white/40 text-firefly/40 mt-2">
                                {t(
                                    'agentSetting.skillSetting.connect.urlFormat.example'
                                )}
                            </p>
                        </div>

                        <div className="space-y-4 grid grid-cols-2 gap-4">
                            <Button
                                type="button"
                                variant="outline"
                                className="h-12 rounded-xl text-base border border-black dark:border-white"
                                onClick={handleCancel}
                            >
                                {t('common.cancel')}
                            </Button>
                            <Button
                                type="submit"
                                className="h-12 rounded-xl bg-sky-blue text-black text-base"
                                disabled={isLoading}
                            >
                                {isLoading
                                    ? t(
                                          'agentSetting.skillSetting.connect.actions.connecting'
                                      )
                                    : t(
                                          'agentSetting.skillSetting.connect.actions.connect'
                                      )}
                            </Button>
                        </div>
                    </form>
                </Form>
            </SheetContent>
        </Sheet>
    )
}

export default ConnectSkill
