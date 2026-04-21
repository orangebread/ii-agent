import { existsSync, readdirSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const execPath = path.resolve(process.execPath)

if (!isCodexBundledNode(execPath)) {
    process.exit(0)
}

const workspaceNodeBin = findWorkspaceNodeBin(process.env.HOME)
const pathPrefix = buildPathPrefix(workspaceNodeBin)
const prefixHint = pathPrefix ? `PATH="${pathPrefix}:$PATH" ` : ''

console.error(
    [
        '',
        'Unsupported Node.js runtime for frontend builds.',
        '',
        `Detected runtime: ${execPath}`,
        '',
        "Codex Desktop's bundled Node.js binary cannot load Rollup's native addon on macOS.",
        'That host process is signed with hardened runtime library validation, so Vite/Rollup',
        'fails with a misleading optional-dependency error instead of building.',
        '',
        'Use a workspace or system Node.js binary instead:',
        workspaceNodeBin
            ? `  Preferred: ${prefixHint}pnpm build`
            : '  Preferred: use the Codex workspace runtime node if it is installed.',
        `  Fallback:  ${prefixHint}npm run build`,
        `  Dev server: ${prefixHint}pnpm dev`,
        '',
        'Do not delete node_modules or regenerate lockfiles for this error.',
        ''
    ].join('\n')
)

process.exit(1)

function isCodexBundledNode(nodePath) {
    return nodePath.includes('/Codex.app/Contents/Resources/node')
}

function buildPathPrefix(workspaceNodeBin) {
    const parts = []

    if (workspaceNodeBin) {
        parts.push(workspaceNodeBin)
    }

    parts.push('/opt/homebrew/bin')

    return parts.join(':')
}

function findWorkspaceNodeBin(homeDir) {
    if (!homeDir) {
        return null
    }

    const runtimesDir = path.join(homeDir, '.cache', 'codex-runtimes')

    if (!existsSync(runtimesDir)) {
        return null
    }

    const runtimeNames = readdirSync(runtimesDir).sort((left, right) => {
        if (left === 'codex-primary-runtime') {
            return -1
        }

        if (right === 'codex-primary-runtime') {
            return 1
        }

        return left.localeCompare(right)
    })

    for (const runtimeName of runtimeNames) {
        const nodeBinDir = path.join(
            runtimesDir,
            runtimeName,
            'dependencies',
            'node',
            'bin'
        )
        const nodeBinary = path.join(nodeBinDir, 'node')

        if (existsSync(nodeBinary)) {
            return nodeBinDir
        }
    }

    return null
}
