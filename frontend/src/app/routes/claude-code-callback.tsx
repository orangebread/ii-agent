import { useEffect } from 'react'
import { useSearchParams } from 'react-router'

export function ClaudeCodeCallback() {
    const [searchParams] = useSearchParams()

    useEffect(() => {
        const code = searchParams.get('code')
        const state = searchParams.get('state')
        const error = searchParams.get('error')
        const errorDescription = searchParams.get('error_description')

        if (window.opener) {
            window.opener.postMessage(
                {
                    type: 'claude-code-auth',
                    code,
                    state,
                    error,
                    errorDescription
                },
                window.location.origin
            )
            window.close()
            return
        }
    }, [searchParams])

    return (
        <div className="flex min-h-screen items-center justify-center">
            <div className="text-center">
                <h2 className="mb-2 text-xl font-semibold">
                    Claude Code Authorization
                </h2>
                <p className="text-gray-600">
                    Authorization completed. Return to the original II-Agent
                    window.
                </p>
            </div>
        </div>
    )
}
