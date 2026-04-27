import React from 'react'
import ReactDOM from 'react-dom/client'
import { PublicClientApplication, EventType } from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { msalConfig } from './auth/msalConfig.js'
import App from './App.jsx'
import AuthGate from './components/AuthGate.jsx'

const msalInstance = new PublicClientApplication(msalConfig)

// Set the active account as soon as login completes so acquireTokenSilent
// can always find it via getActiveAccount() without needing to search accounts[].
msalInstance.addEventCallback((event) => {
  if (event.eventType === EventType.LOGIN_SUCCESS && event.payload?.account) {
    msalInstance.setActiveAccount(event.payload.account)
  }
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <MsalProvider instance={msalInstance}>
      <AuthGate>
        <App />
      </AuthGate>
    </MsalProvider>
  </React.StrictMode>
)
