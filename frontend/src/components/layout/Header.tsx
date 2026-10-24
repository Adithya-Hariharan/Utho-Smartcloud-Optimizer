import { FlaskConical, PlugZap } from 'lucide-react'
import { useSource } from '../../store/source'
import { useAssumptions } from '../../api/data'
import { useRecs } from '../../api/recs'
import { useNavigate } from 'react-router-dom'
import { ROLE_HOME, useUi, type Role } from '../../store/ui'
import type { PresetId } from '../../types/contract'

export function Header() {
  const meta = useAssumptions()
  const recs = useRecs()
  const fallback = useSource((s) => s.fallback)
  const preset = useUi((s) => s.preset)
  const setPreset = useUi((s) => s.setPreset)
  const role = useUi((s) => s.role)
  const setRole = useUi((s) => s.setRole)
  const navigate = useNavigate()

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-slate-200 bg-white px-6">
      {fallback && (
        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-review-600/30 bg-review-50 px-2.5 py-1 text-2xs font-semibold text-review-700"
          title="The backend is not running, so the dev server is answering from fallback data (built from data/ by the reference engine). The app switches to the backend by itself when it starts."
          data-testid="fallback-banner"
        >
          <PlugZap size={12} /> Fallback data · backend offline
        </span>
      )}
      {!fallback && recs.data?.mock_engine && (
        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-review-600/30 bg-review-50 px-2.5 py-1 text-2xs font-semibold text-review-700"
          title="The backend reports mock_engine: true. Its recommendations are not from the real engine yet."
          data-testid="mock-banner"
        >
          <FlaskConical size={12} /> Mock engine
        </span>
      )}
      <div className="flex-1" />
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <span className="label">View as</span>
        <select
          className="input py-1"
          value={role}
          onChange={(e) => {
            const r = e.target.value as Role
            setRole(r)
            navigate(ROLE_HOME[r])
          }}
          aria-label="Role"
          data-testid="role-select"
        >
          <option value="engineer">Engineer</option>
          <option value="finance">Finance</option>
          <option value="leadership">Leadership</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <span className="label">Preset</span>
        <select
          className="input py-1"
          value={preset}
          onChange={(e) => setPreset(e.target.value as PresetId)}
          aria-label="Preset"
          data-testid="preset-select"
        >
          {meta.data?.presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          )) ?? <option value={preset}>{preset}</option>}
        </select>
      </label>
    </header>
  )
}
