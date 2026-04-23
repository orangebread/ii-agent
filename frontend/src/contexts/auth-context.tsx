import { ACCESS_TOKEN } from '@/constants/auth'
import {
    getPreferredModelIdForFeature,
    getSelectableModels
} from '@/constants/models'
import { authService } from '@/services/auth.service'
import { settingsService } from '@/services/settings.service'
import {
    selectSelectedModel,
    selectSelectedFeature,
    setAvailableModels,
    setSelectedModel,
    store,
    userApi,
    sessionApi
} from '@/state'
import { useAppDispatch, useAppSelector } from '@/state/store'
import { setUser, clearUser, setLoading } from '@/state/slice/user'
import type { User } from '@/state/slice/user'
import { fetchWishlist, clearFavorites } from '@/state/slice/favorites'
import { fetchPins, clearPins } from '@/state/slice/pins'
import { createContext, useContext, useEffect, ReactNode, useCallback } from 'react'

interface AuthContextType {
    user: User | null
    isAuthenticated: boolean
    completeTokenLogin: (accessToken: string) => Promise<void>
    loginWithAuthCode: (authCode: string) => Promise<void>
    refreshAvailableModels: () => Promise<void>
    logout: () => void
    isLoading: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const dispatch = useAppDispatch()
    const { user, isLoading } = useAppSelector((state) => state.user)

    // Derive isAuthenticated from the presence of a valid access token
    const isAuthenticated = !!localStorage.getItem(ACCESS_TOKEN)

    const fetchAvailableModels = useCallback(async () => {
        try {
            const data = await settingsService.getAvailableModels()
            const selectableModels = getSelectableModels(data?.models || [])
            dispatch(setAvailableModels(selectableModels))

            const state = store.getState()
            const currentSelectedModel = selectSelectedModel(state)
            const selectedFeature = selectSelectedFeature(state)
            const nextSelectedModelId = getPreferredModelIdForFeature(
                selectableModels,
                selectedFeature,
                currentSelectedModel
            )
            dispatch(setSelectedModel(nextSelectedModelId))
        } catch (error) {
            console.log('Failed to fetch llm models', error)
        }
    }, [dispatch])

    const completeTokenLogin = useCallback(
        async (accessToken: string) => {
            localStorage.setItem(ACCESS_TOKEN, accessToken)
            window.dispatchEvent(new CustomEvent('auth-token-set'))

            const userRes = await authService.getCurrentUser()
            dispatch(setUser(userRes))
            await fetchAvailableModels()
            dispatch(fetchWishlist())
            dispatch(fetchPins())
        },
        [dispatch, fetchAvailableModels]
    )

    useEffect(() => {
        const initializeAuth = async () => {
            try {
                const accessToken = localStorage.getItem(ACCESS_TOKEN)

                if (accessToken) {
                    try {
                        const userRes = await authService.getCurrentUser()
                        dispatch(setUser(userRes))
                        await fetchAvailableModels()
                        // Fetch user's wishlist and pins after successful authentication
                        dispatch(fetchWishlist())
                        dispatch(fetchPins())
                    } catch (apiError) {
                        console.error(
                            'Failed to get current user from API:',
                            apiError
                        )
                        const storedUser = localStorage.getItem('user')
                        if (storedUser) {
                            const userData = JSON.parse(storedUser)
                            dispatch(setUser(userData))
                            // Try to fetch wishlist and pins even with cached user data
                            dispatch(fetchWishlist())
                            dispatch(fetchPins())
                        } else {
                            dispatch(setLoading(false))
                        }
                    }
                } else {
                    dispatch(setLoading(false))
                }
            } catch (error) {
                console.error('Error initializing auth:', error)
                dispatch(setLoading(false))
            }
        }

        initializeAuth()
    }, [dispatch, fetchAvailableModels])

    const loginWithAuthCode = async (code: string) => {
        try {
            const res = await authService.googleAuth({
                code,
                redirect_uri: window.location.origin
            })
            await completeTokenLogin(res.access_token)
        } catch (error) {
            console.error('Error handling auth code:', error)
            throw error
        }
    }

    const logout = () => {
        localStorage.removeItem(ACCESS_TOKEN)
        dispatch(clearUser())
        dispatch(clearFavorites())
        dispatch(clearPins())
        // Reset all RTK Query cache to prevent data leakage between users
        dispatch(userApi.util.resetApiState())
        dispatch(sessionApi.util.resetApiState())
    }

    const value: AuthContextType = {
        user,
        isAuthenticated,
        completeTokenLogin,
        loginWithAuthCode,
        refreshAvailableModels: fetchAvailableModels,
        logout,
        isLoading
    }

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider')
    }
    return context
}
