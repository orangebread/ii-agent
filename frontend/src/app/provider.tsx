import { ReactNode, Suspense } from 'react'
import { ThemeProvider } from 'next-themes'
import { GoogleOAuthProvider } from '@react-oauth/google'
import AppErrorPage from '@/features/errors/app-error'
import { ErrorBoundary } from 'react-error-boundary'
import { TooltipProvider } from '@/components/ui/tooltip'
import { TerminalProvider } from '@/contexts/terminal-context'
import { AuthProvider } from '@/contexts/auth-context'
import { getGoogleOAuthClientId } from '@/lib/google-oauth'

function MaybeGoogleOAuthProvider({ children }: { children: ReactNode }) {
    const googleClientId = getGoogleOAuthClientId()

    if (!googleClientId) {
        return <>{children}</>
    }

    return (
        <GoogleOAuthProvider clientId={googleClientId}>
            {children}
        </GoogleOAuthProvider>
    )
}

export default function AppProvider({ children }: { children: ReactNode }) {
    return (
        <Suspense fallback={<>Loading...</>}>
            <ErrorBoundary FallbackComponent={AppErrorPage}>
                <MaybeGoogleOAuthProvider>
                    <AuthProvider>
                        <ThemeProvider
                            attribute="class"
                            defaultTheme="system"
                            enableSystem
                        >
                            <TerminalProvider>
                                <TooltipProvider>{children}</TooltipProvider>
                            </TerminalProvider>
                        </ThemeProvider>
                    </AuthProvider>
                </MaybeGoogleOAuthProvider>
            </ErrorBoundary>
        </Suspense>
    )
}
