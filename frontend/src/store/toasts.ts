import { create } from 'zustand'

export interface Toast { id: number; title: string; body?: string; tone?: 'info' | 'warn' }

interface ToastState {
  toasts: Toast[]
  push: (t: Omit<Toast, 'id'>) => void
  dismiss: (id: number) => void
}

let next = 1
export const useToasts = create<ToastState>()((set) => ({
  toasts: [],
  push: (t) => {
    const id = next++
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), 9000)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}))
