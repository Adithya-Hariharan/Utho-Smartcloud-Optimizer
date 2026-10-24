import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PresetId } from '../types/contract'

/** PLAN §11 role switch: decides the landing page and which pages come first. */
export type Role = 'engineer' | 'finance' | 'leadership'
export const ROLE_HOME: Record<Role, string> = { engineer: '/recommendations', finance: '/what-if', leadership: '/' }

interface UiState {
  preset: PresetId
  setPreset: (p: PresetId) => void
  role: Role
  setRole: (r: Role) => void
}

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      preset: 'default',
      setPreset: (preset) => set({ preset }),
      role: 'engineer',
      setRole: (role) => set({ role }),
    }),
    { name: 'smartcloud.ui' },
  ),
)
