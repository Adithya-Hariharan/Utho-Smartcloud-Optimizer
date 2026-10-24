import { create } from 'zustand'

/**
 * Where the last API response came from. "fallback" means the dev server answered from
 * fallback/api/ because the backend is not running (TEMPORARY; see vite.config.ts).
 */
interface SourceState {
  fallback: boolean
  setFallback: (v: boolean) => void
}

export const useSource = create<SourceState>()((set) => ({
  fallback: false,
  setFallback: (fallback) => set((s) => (s.fallback === fallback ? s : { fallback })),
}))
