import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, X } from 'lucide-react'

export interface FilterDef {
  key: string
  label: string
  options: { value: string; label: string }[]
}

/** Filters live in the URL (?env=dev&team=growth), so views are shareable and survive reloads. */
export function useUrlFilters(keys: string[]) {
  const [params, setParams] = useSearchParams()
  const values = useMemo(() => Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ''])), [params, keys])
  const set = (key: string, value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )
  const clear = () =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        keys.forEach((k) => next.delete(k))
        return next
      },
      { replace: true },
    )
  return { values, set, clear, active: keys.some((k) => params.get(k)) }
}

export function FilterBar({ defs, filters, search = true, right }: { defs: FilterDef[]; filters: ReturnType<typeof useUrlFilters>; search?: boolean; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Filters">
      {defs.map((d) => (
        <select
          key={d.key}
          className="input input-sm max-w-[150px] max-sm:min-w-[calc(50%-4px)] max-sm:max-w-none max-sm:flex-1"
          aria-label={d.label}
          data-testid={`filter-${d.key}`}
          value={filters.values[d.key]}
          onChange={(e) => filters.set(d.key, e.target.value)}
        >
          <option value="">{d.label}: all</option>
          {d.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ))}
      {search && (
        <label className="relative max-sm:w-full">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden />
          <input
            className="input input-sm w-44 pl-8 max-sm:w-full"
            placeholder="Search name…"
            aria-label="Search by name"
            value={filters.values.q ?? ''}
            onChange={(e) => filters.set('q', e.target.value)}
          />
        </label>
      )}
      {filters.active && (
        <button className="btn-ghost btn-sm" onClick={filters.clear}>
          <X size={12} /> Clear filters
        </button>
      )}
      <div className="flex-1 max-sm:hidden" />
      {right}
    </div>
  )
}

export function distinct<T>(rows: T[], get: (r: T) => string | null | undefined, label: (v: string) => string = (v) => v) {
  const set = new Set<string>()
  rows.forEach((r) => set.add(get(r) || ''))
  return [...set].sort().map((v) => ({ value: v || '__none', label: v ? label(v) : 'Untagged / unowned' }))
}

export const matches = (filterValue: string, actual: string | null | undefined) =>
  !filterValue || (filterValue === '__none' ? !actual : actual === filterValue)
