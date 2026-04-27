import { useEffect } from 'react'
import { useIsAuthenticated, useMsal } from '@azure/msal-react'
import { InteractionStatus, InteractionRequiredAuthError } from '@azure/msal-browser'
import { loginRequest } from '../auth/msalConfig.js'
import { setTokenProvider } from '../api.js'

export default function AuthGate({ children }) {
  const { instance, inProgress } = useMsal()
  const isAuthenticated = useIsAuthenticated()

  // Wire the token provider as soon as MSAL finishes initialising.
  useEffect(() => {
    if (!isAuthenticated) return
    setTokenProvider(async () => {
      try {
        const result = await instance.acquireTokenSilent(loginRequest)
        return result.accessToken
      } catch (err) {
        if (err instanceof InteractionRequiredAuthError) {
          // Cached token expired or consent needed — restart the login flow.
          instance.loginRedirect(loginRequest)
          return null
        }
        throw err
      }
    })
    return () => setTokenProvider(null)
  }, [isAuthenticated, instance])

  // MSAL is still loading (redirect/popup in flight)
  if (inProgress !== InteractionStatus.None) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-950">
        <p className="text-gray-400 text-sm">Signing in…</p>
      </div>
    )
  }

  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-950 gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-white mb-1">EDGAR</h1>
          <p className="text-gray-400 text-sm">Sign in with your LPA account to continue</p>
        </div>
        <button
          onClick={() => instance.loginRedirect(loginRequest)}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          Sign in with Microsoft
        </button>
      </div>
    )
  }

  return children
}
