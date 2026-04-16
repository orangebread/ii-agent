import { Link, useNavigate } from 'react-router'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useTranslation } from 'react-i18next'

import { useAuth } from '@/contexts/auth-context'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import { Form, FormControl, FormField, FormItem } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { GoogleAuthButton } from '@/components/auth/google-auth-button'
import { isGoogleOAuthConfigured } from '@/lib/google-oauth'

const FormSchema = z.object({
    name: z.string({ error: 'Name is required' }).min(1, {
        message: 'Name is required'
    }),
    email: z.email({ error: 'Invalid email address' }),
    password: z.string({ error: 'Password is required' }).min(6, {
        message: 'Password must be at least 6 characters'
    })
})

export function SignupPage() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { loginWithAuthCode } = useAuth()

    const form = useForm<z.infer<typeof FormSchema>>({
        resolver: zodResolver(FormSchema),
        defaultValues: {
            name: '',
            email: '',
            password: ''
        }
    })

    const googleOAuthEnabled = isGoogleOAuthConfigured()

    const onSubmit = async (data: z.infer<typeof FormSchema>) => {
        console.log(data)
    }

    return (
        <div className="flex flex-col items-center justify-center w-full h-full">
            <h1 className="text-[32px] font-semibold text-firefly dark:text-sky-blue">
                Welcome to II-Agent
            </h1>
            <p className="text-[28px] text-firefly dark:text-sky-blue mb-12">
                Helping you with your task today
            </p>

            <div className="flex flex-col w-full justify-center max-w-[510px]">
                <Form {...form}>
                    <form
                        onSubmit={form.handleSubmit(onSubmit)}
                        className="flex flex-col gap-10"
                    >
                        <div className="space-y-6">
                            <FormField
                                control={form.control}
                                name="name"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormControl>
                                            <div className="space-y-2 relative">
                                                <Icon
                                                    name="user"
                                                    className="absolute top-3 left-4 fill-black dark:fill-white"
                                                />
                                                <Input
                                                    id="name"
                                                    className="pl-[56px]"
                                                    type="text"
                                                    placeholder="Enter your name"
                                                    {...field}
                                                />
                                            </div>
                                        </FormControl>
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="email"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormControl>
                                            <div className="space-y-2 relative">
                                                <Icon
                                                    name="email"
                                                    className="absolute top-3 left-4 fill-black dark:fill-white"
                                                />
                                                <Input
                                                    id="email"
                                                    className="pl-[56px]"
                                                    type="text"
                                                    placeholder="Enter your email address"
                                                    {...field}
                                                />
                                            </div>
                                        </FormControl>
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="password"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormControl>
                                            <div className="space-y-2 relative">
                                                <Icon
                                                    name="key"
                                                    className="absolute top-3 left-4 fill-black dark:fill-white"
                                                />
                                                <Input
                                                    id="password"
                                                    className="pl-[56px]"
                                                    type="password"
                                                    placeholder="Enter your password"
                                                    {...field}
                                                />
                                            </div>
                                        </FormControl>
                                    </FormItem>
                                )}
                            />
                        </div>
                        <div className="w-full flex justify-center">
                            <Button
                                type="submit"
                                size="xl"
                                className=" bg-firefly text-sky-blue-2 dark:bg-sky-blue dark:text-black font-semibold w-full max-w-[247px]"
                                disabled={!form.formState.isValid}
                            >
                                Sign up
                            </Button>
                        </div>
                    </form>
                </Form>
                <div className="flex justify-center items-center gap-2 text-black dark:text-white text-sm mt-8">
                    <span>Already have an account?</span>
                    <Link
                        to="/login"
                        className="text-black dark:text-white text-sm font-semibold"
                    >
                        Sign in
                    </Link>
                </div>
                <div className="flex w-full items-center gap-4 my-10">
                    <p className="flex-1 bg-black/[0.31] dark:bg-white/[0.31] h-[1px]"></p>
                    <span className="text-sm text-black dark:text-white font-semibold">
                        {t('common.or')}
                    </span>
                    <p className="flex-1 bg-black/[0.31] dark:bg-white/[0.31] h-[1px]"></p>
                </div>
                <p className="text-xs text-center text-firefly/70 dark:text-sky-blue/70 mb-6">
                    {t('auth.privacyNotice')}{' '}
                    <a
                        href="/privacy"
                        className="underline hover:text-firefly dark:hover:text-sky-blue"
                    >
                        {t('auth.privacyNoticeLink')}
                    </a>
                </p>
                {googleOAuthEnabled ? (
                    <GoogleAuthButton
                        className="w-full bg-white text-black font-semibold shadow-btn"
                        label={t('auth.continueWithGoogle')}
                        onAuthCode={async (authCode) => {
                            await loginWithAuthCode(authCode)
                            navigate('/')
                        }}
                    />
                ) : (
                    <p className="text-center text-sm text-firefly/70 dark:text-sky-blue/70">
                        Google sign-in is unavailable in this local environment
                        because `VITE_GOOGLE_CLIENT_ID` is not configured.
                    </p>
                )}
            </div>
        </div>
    )
}

export const Component = SignupPage
