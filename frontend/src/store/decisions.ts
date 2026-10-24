// Accept/reject decisions live in the browser (PLAN §1: no server write path).
// Keyed by resource_id, not rec_id, so they survive a preset switch; see reconcile() for F8.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Decisions } from '../lib/cost'
import type { Recommendation } from '../types/contract'

interface DecisionState {
  decisions: Decisions
  accept: (r: Recommendation, optionKey?: string) => void
  reject: (r: Recommendation) => void
  clear: (resourceId: string) => void
  acceptMany: (rs: Recommendation[]) => void
  replaceAll: (d: Decisions) => void
  resetAll: () => void
}

export const useDecisions = create<DecisionState>()(
  persist(
    (set) => ({
      decisions: {},
      accept: (r, optionKey) =>
        set((s) => ({
          decisions: {
            ...s.decisions,
            [r.resource.resource_id]: {
              resourceId: r.resource.resource_id,
              status: 'accepted',
              optionKey: optionKey ?? r.default_option,
              targetPlan: r.target?.plan ?? null,
            },
          },
        })),
      reject: (r) =>
        set((s) => ({
          decisions: {
            ...s.decisions,
            [r.resource.resource_id]: { resourceId: r.resource.resource_id, status: 'rejected', optionKey: 'none', targetPlan: null },
          },
        })),
      clear: (id) =>
        set((s) => {
          const next = { ...s.decisions }
          delete next[id]
          return { decisions: next }
        }),
      acceptMany: (rs) =>
        set((s) => {
          const next = { ...s.decisions }
          for (const r of rs)
            next[r.resource.resource_id] = { resourceId: r.resource.resource_id, status: 'accepted', optionKey: r.default_option, targetPlan: r.target?.plan ?? null }
          return { decisions: next }
        }),
      replaceAll: (decisions) => set({ decisions }),
      resetAll: () => set({ decisions: {} }),
    }),
    { name: 'smartcloud.decisions' },
  ),
)
