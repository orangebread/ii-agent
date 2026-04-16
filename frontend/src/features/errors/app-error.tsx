import { Button } from '@/components/ui/button'
import {
    ErrorView,
    ErrorHeader,
    ErrorDescription,
    ErrorActions
} from '@/features/errors/error-base'

export default function AppErrorPage() {
    return (
        <ErrorView>
            <ErrorHeader>Something went wrong</ErrorHeader>
            <ErrorDescription>
                The app hit an unexpected error.
                <br />
                Reload the page and try again.
            </ErrorDescription>
            <ErrorActions>
                <Button size="lg" onClick={() => window.location.reload()}>
                    Reload page
                </Button>
            </ErrorActions>
        </ErrorView>
    )
}
