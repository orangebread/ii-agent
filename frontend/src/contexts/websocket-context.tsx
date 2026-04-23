import {
    createContext,
    useContext,
    useEffect,
    ReactNode,
    useCallback,
    useRef,
    useState
} from 'react'
import { useLocation, useParams } from 'react-router'
import { toast } from 'sonner'
import { io, Socket, ManagerOptions, SocketOptions } from 'socket.io-client'
import {
    AgentEvent,
    WebSocketConnectionState,
    ChatMessagePayload
} from '@/typings/agent'
import { useAppDispatch, useAppSelector } from '@/state/store'
import {
    selectIsFromNewQuestion,
    selectActiveSessionId,
    selectWsConnectionState,
    setAgentInitialized,
    setWsConnectionState
} from '@/state'
import { ACCESS_TOKEN } from '@/constants/auth'

interface SocketIOContextType {
    socket: Socket | null
    isSessionReady: boolean
    connectSocket: () => void
    sendMessage: (payload: ChatMessagePayload) => boolean
    joinSession: () => void
}

const SocketIOContext = createContext<SocketIOContextType | null>(null)

interface SocketIOProviderProps {
    children: ReactNode
    handleEvent: (data: {
        id: string
        name: AgentEvent
        content: Record<string, unknown>
    }) => void
}

export function SocketIOProvider({
    children,
    handleEvent
}: SocketIOProviderProps) {
    const { sessionId } = useParams()
    const location = useLocation()
    const isFromNewQuestion = useAppSelector(selectIsFromNewQuestion)
    const activeSessionId = useAppSelector(selectActiveSessionId)
    const wsConnectionState = useAppSelector(selectWsConnectionState)
    const currentSessionId = sessionId || activeSessionId || undefined
    const [socket, setSocket] = useState<Socket | null>(null)
    const [isSessionReady, setIsSessionReady] = useState(false)
    const connectionRef = useRef<Socket | null>(null)
    const isConnectingRef = useRef(false)
    const handleEventRef = useRef(handleEvent)
    const sessionIdRef = useRef<string | undefined>(currentSessionId)
    const isFromNewQuestionRef = useRef(isFromNewQuestion)
    const dispatch = useAppDispatch()
    const sessionInitializedRef = useRef(false)
    const shouldDisableJoinSession = location.pathname.includes('/chat')
    const shouldDisableJoinSessionRef = useRef(shouldDisableJoinSession)
    shouldDisableJoinSessionRef.current = shouldDisableJoinSession

    // Update the refs when values change
    handleEventRef.current = handleEvent
    isFromNewQuestionRef.current = isFromNewQuestion

    // Keep sessionIdRef in sync with sessionId (from URL params) or activeSessionId (from Redux)
    // Priority: sessionId (URL is source of truth) > activeSessionId (fallback for home page)
    useEffect(() => {
        sessionInitializedRef.current = false
        sessionIdRef.current = currentSessionId
        setIsSessionReady(false)

        if (currentSessionId) {
            console.log(
                'WebSocket: Resetting isAgentInitialized for session change:',
                currentSessionId
            )
            dispatch(setAgentInitialized(false))
        }
    }, [currentSessionId, dispatch])

    const connectSocket = useCallback(() => {
        // Prevent duplicate connections - check if already connected or connecting
        if (connectionRef.current?.connected || isConnectingRef.current) {
            console.log(
                'Socket.IO already connected or connecting, skipping',
                connectionRef.current?.id
            )
            return
        }

        // Clean up any existing connection first
        if (connectionRef.current) {
            console.log(
                'Cleaning up existing connection:',
                connectionRef.current.id
            )
            connectionRef.current.removeAllListeners()
            connectionRef.current.disconnect()
            connectionRef.current = null
            setSocket(null)
        }

        // Reset session initialization flag when reconnecting
        sessionInitializedRef.current = false
        setIsSessionReady(false)

        dispatch(setWsConnectionState(WebSocketConnectionState.CONNECTING))
        const token = localStorage.getItem(ACCESS_TOKEN)
        if (!token) {
            console.log('WebSocket: No token available, skipping connection')
            dispatch(
                setWsConnectionState(WebSocketConnectionState.DISCONNECTED)
            )
            return
        }

        console.log(
            'WebSocket: Token found, establishing connection immediately'
        )
        // Reset agent initialization state when connecting
        dispatch(setAgentInitialized(false))

        isConnectingRef.current = true

        const socketOptions: Partial<ManagerOptions & SocketOptions> = {
            auth: (cb) => {
                const freshToken = localStorage.getItem(ACCESS_TOKEN) ?? ''
                const data: Record<string, string> = { token: freshToken }
                if (sessionIdRef.current && !isFromNewQuestionRef.current) {
                    data.session_uuid = sessionIdRef.current
                }
                cb(data)
            },
            transports: ['websocket'],
            timeout: 15000,
            reconnection: true,
            reconnectionAttempts: 10,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 30000
        }

        const socketInstance = io(import.meta.env.VITE_API_URL, socketOptions)

        socketInstance.on('connect', () => {
            console.log('Socket.IO connection established, ID:', socketInstance.id)
            isConnectingRef.current = false
            dispatch(setWsConnectionState(WebSocketConnectionState.CONNECTED))

            // Initialize the session on connect when a sessionId exists
            if (sessionIdRef.current && !sessionInitializedRef.current && !shouldDisableJoinSessionRef.current) {
                console.log('Emitting join_session for:', sessionIdRef.current)
                socketInstance.emit('join_session', {
                    session_uuid: sessionIdRef.current
                })
                sessionInitializedRef.current = true
            }
        })

        socketInstance.on('chat_event', (data) => {
            try {
                if (
                    data?.name === AgentEvent.CONNECTION_ESTABLISHED &&
                    typeof data?.content?.session_id === 'string'
                ) {
                    setIsSessionReady(true)
                }
                handleEventRef.current({ ...data, id: Date.now().toString() })
            } catch (error) {
                console.error('Error handling Socket.IO event:', error)
            }
        })

        socketInstance.on('connect_error', (error) => {
            console.log('Socket.IO connection error:', error)
            isConnectingRef.current = false
            setIsSessionReady(false)
            dispatch(
                setWsConnectionState(WebSocketConnectionState.DISCONNECTED)
            )
        })

        socketInstance.on('disconnect', (reason) => {
            console.log(
                'Socket.IO disconnected:',
                reason,
                'Socket ID:',
                socketInstance.id
            )
            dispatch(
                setWsConnectionState(WebSocketConnectionState.DISCONNECTED)
            )
            sessionInitializedRef.current = false
            setIsSessionReady(false)
            // Socket.IO will auto-reconnect; keep connectionRef intact
        })

        setSocket(socketInstance)
        connectionRef.current = socketInstance
    }, [dispatch])

    const joinSession = useCallback(() => {
        if (shouldDisableJoinSession) {
            console.log(
                'Skipping join_session: current path includes /chat'
            )
            sessionInitializedRef.current = true
            setIsSessionReady(true)
            return
        }

        if (!socket || !socket.connected) {
            console.error('Cannot initialize session: Socket not connected')
            return
        }

        // Always emit initialize_session to ensure server-side session is ready
        // The server should handle duplicate initializations gracefully
        console.log('Joining session...')
        setIsSessionReady(false)
        socket.emit('join_session', {
            session_uuid: sessionIdRef.current
        })
        sessionInitializedRef.current = true
    }, [socket, shouldDisableJoinSession])

    const sendMessage = useCallback(
        (payload: ChatMessagePayload) => {
            if (!socket || !socket.connected) {
                toast.error(
                    'Socket.IO connection is not open. Please try again.'
                )
                return false
            }

            // Ensure session_uuid is set from current session
            const message: ChatMessagePayload = {
                ...payload,
                session_uuid:
                    payload.session_uuid || sessionIdRef.current || ''
            }

            socket.emit('chat_message', message)
            return true
        },
        [socket]
    )

    // Connect once on mount
    useEffect(() => {
        connectSocket()

        // Cleanup on unmount
        return () => {
            if (connectionRef.current) {
                connectionRef.current.removeAllListeners()
                connectionRef.current.disconnect()
                connectionRef.current = null
                isConnectingRef.current = false
                setSocket(null)
            }
        }
    }, [connectSocket])

    // Initialize session when sessionId changes and socket is connected (for existing sessions on page reload)
    useEffect(() => {
        const isConnected = wsConnectionState === WebSocketConnectionState.CONNECTED
        if (isConnected && sessionId && !sessionInitializedRef.current) {
            console.log(
                'Initializing session due to sessionId change or connection established:',
                sessionId
            )
            joinSession()
        }
    }, [sessionId, wsConnectionState, joinSession])

    return (
        <SocketIOContext.Provider
            value={{
                socket,
                isSessionReady,
                connectSocket,
                sendMessage,
                joinSession
            }}
        >
            {children}
        </SocketIOContext.Provider>
    )
}

export function useSocketIOContext() {
    const context = useContext(SocketIOContext)
    if (!context) {
        throw new Error(
            'useSocketIOContext must be used within a SocketIOProvider'
        )
    }
    return context
}

// Backward compatibility alias
export const useWebSocketContext = useSocketIOContext
export const WebSocketProvider = SocketIOProvider
