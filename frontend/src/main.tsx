import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ApiError } from './api/client'
import './index.css'

// retry once on network trouble; a 4xx from the backend is an answer, not a glitch
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: (n, e) => n < 1 && !(e instanceof ApiError && e.status !== null && e.status < 500), refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
