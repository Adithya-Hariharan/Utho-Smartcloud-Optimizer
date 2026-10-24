import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSource } from '../../store/source'
import { useToasts } from '../../store/toasts'

/**
 * While the app is on fallback data, ask the dev server every few seconds whether the backend
 * is up. The moment it is, refetch everything so every page switches to live data.
 */
export function BackendWatcher() {
  const fallback = useSource((s) => s.fallback)
  const queryClient = useQueryClient()
  const push = useToasts((s) => s.push)

  useEffect(() => {
    if (!fallback) return
    let stop = false
    const tick = async () => {
      try {
        const res = await fetch('/api/__health')
        const { backend } = (await res.json()) as { backend: boolean }
        if (backend && !stop) {
          stop = true
          await queryClient.invalidateQueries()
          push({ title: 'Backend connected', body: 'Showing live data from the API.' })
        }
      } catch {
        // dev server restarting; try again on the next tick
      }
    }
    const t = setInterval(tick, 4000)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [fallback, queryClient, push])

  return null
}
