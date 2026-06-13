import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { AuthProvider } from './auth'
import './styles/fonts.css'
import './styles/kg-tokens.css'
import './styles/harness.css'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider baseUrl={apiBaseUrl}>
      <App />
    </AuthProvider>
  </StrictMode>,
)
