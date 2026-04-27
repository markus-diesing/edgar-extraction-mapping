import React from 'react'
import ReactDOM from 'react-dom/client'
import { PublicClientApplication } from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { msalConfig } from './auth/msalConfig.js'
import App from './App.jsx'
import AuthGate from './components/AuthGate.jsx'

const msalInstance = new PublicClientApplication(msalConfig)

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <MsalProvider instance={msalInstance}>
      <AuthGate>
        <App />
      </AuthGate>
    </MsalProvider>
  </React.StrictMode>
)
