// Start der Oberfläche; main.tsx lädt diese Datei erst nach dem Sprachkatalog.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthContext.tsx'
import { OrgProvider } from './org/OrgContext.tsx'
import './theme/theme.css'
import './index.css'
import { watchTableSemantics } from './components/tableSemantics.ts'

watchTableSemantics()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
