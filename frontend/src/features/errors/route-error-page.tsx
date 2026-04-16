import {
    isRouteErrorResponse,
    useNavigate,
    useRouteError
} from 'react-router'

import { Button } from '@/components/ui/button'
import {
    ErrorActions,
    ErrorDescription,
    ErrorHeader,
    ErrorView
} from '@/features/errors/error-base'

export default function RouteErrorPage() {
    const navigate = useNavigate()
    const error = useRouteError()

    const title = isRouteErrorResponse(error)
        ? `${error.status} ${error.statusText}`
        : 'Something went wrong'
    const description = isRouteErrorResponse(error)
        ? error.data?.message || error.data?.detail || 'The page could not be loaded.'
        : error instanceof Error
          ? error.message
          : 'The page could not be loaded.'

    return (
        <ErrorView className="bg-slate-50">
            <ErrorHeader>{title}</ErrorHeader>
            <ErrorDescription>
                {description}
                <br />
                Reload the page or return home and try again.
            </ErrorDescription>
            <ErrorActions>
                <Button size="lg" variant="outline" onClick={() => navigate('/')}>
                    Go Home
                </Button>
                <Button size="lg" onClick={() => window.location.reload()}>
                    Reload Page
                </Button>
            </ErrorActions>
        </ErrorView>
    )
}
