import { useLayoutEffect, useRef, useState, type HTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { AlertCircle, Info, RefreshCw, ServerOff } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import type { Risk, Verdict } from '../../types/contract'
import { ApiError } from '../../api/client'
import { VERDICT_META } from '../../lib/labels'

/** Hover/focus tooltip rendered in a portal so tables and drawers never clip it. */
export function Tip({ content, children, className }: { content: ReactNode; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ x: number; y: number; below: boolean } | null>(null)
  const show = () => {
    const r = ref.current?.getBoundingClientRect()
    if (r) setPos({ x: r.left + r.width / 2, y: r.top < 140 ? r.bottom : r.top, below: r.top < 140 })
  }
  return (
    <span ref={ref} className={clsx('inline-flex', className)} onMouseEnter={show} onMouseLeave={() => setPos(null)} onFocus={show} onBlur={() => setPos(null)} tabIndex={0}>
      {children}
      {pos &&
        createPortal(
          <TipBubble x={pos.x} y={pos.y} below={pos.below}>
            {content}
          </TipBubble>,
          document.body,
        )}
    </span>
  )
}

function TipBubble({ x, y, below, children }: { x: number; y: number; below: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [left, setLeft] = useState(x)
  useLayoutEffect(() => {
    const w = ref.current?.offsetWidth ?? 0
    setLeft(Math.min(Math.max(x, w / 2 + 8), window.innerWidth - w / 2 - 8))
  }, [x])
  return (
    <div
      ref={ref}
      role="tooltip"
      className="pointer-events-none fixed z-[100] max-w-sm animate-fade-in rounded-md bg-slate-800 px-3 py-2 text-xs leading-relaxed text-slate-100 shadow-pop ring-1 ring-white/15"
      style={{ left, top: below ? y + 8 : y - 8, transform: `translate(-50%, ${below ? '0' : '-100%'})` }}
    >
      {children}
    </div>
  )
}

/** A number with a "how computed" tooltip. */
export function HowTip({ how, children }: { how: ReactNode; children: ReactNode }) {
  return (
    <Tip content={how}>
      <span className="inline-flex cursor-help items-center gap-1">
        {children}
        <Info size={12} className="text-slate-400" aria-hidden />
      </span>
    </Tip>
  )
}

/** One badge set for every status word in the app. A tone is always shown with its word. */
export type Tone = 'save' | 'review' | 'danger' | 'kept' | 'healthy' | 'upsize' | 'neutral' | 'brand'
const TONE: Record<Tone, { cls: string; dot: string }> = {
  save: { cls: 'bg-save-50 text-save-700 ring-save-600/25', dot: 'bg-save-600' },
  review: { cls: 'bg-review-50 text-review-700 ring-review-600/25', dot: 'bg-review-600' },
  danger: { cls: 'bg-danger-50 text-danger-700 ring-danger-600/25', dot: 'bg-danger-600' },
  kept: { cls: 'bg-kept-50 text-kept-700 ring-kept-600/25', dot: 'bg-kept-600' },
  healthy: { cls: 'bg-healthy-50 text-healthy-700 ring-healthy-600/25', dot: 'bg-healthy-600' },
  upsize: { cls: 'bg-upsize-50 text-upsize-700 ring-upsize-600/25', dot: 'bg-upsize-600' },
  neutral: { cls: 'bg-slate-100 text-slate-600 ring-slate-400/30', dot: 'bg-slate-400' },
  brand: { cls: 'bg-sky-50 text-sky-700 ring-sky-500/25', dot: 'bg-sky-500' },
}

export function Badge({ tone = 'neutral', dot = false, icon, children, className, ...rest }: { tone?: Tone; dot?: boolean; icon?: ReactNode; children: ReactNode; className?: string } & HTMLAttributes<HTMLSpanElement>) {
  const t = TONE[tone]
  return (
    <span {...rest} className={clsx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset', t.cls, className)}>
      {dot && <span className={clsx('h-1.5 w-1.5 rounded-full', t.dot)} aria-hidden />}
      {icon}
      {children}
    </span>
  )
}

export function VerdictBadge({ verdict, label }: { verdict: Verdict; label?: string }) {
  const m = VERDICT_META[verdict]
  return (
    <Badge tone={m.tone} dot>
      {label ?? m.label}
    </Badge>
  )
}

const RISK_TONE: Record<Risk['level'], Tone> = { Low: 'save', Medium: 'review', High: 'danger' }

export function RiskChip({ risk }: { risk: Risk | null }) {
  if (!risk) return <span className="text-slate-500">—</span>
  return (
    <Tip
      content={
        <div>
          <div className="mb-1 font-semibold">
            Risk {risk.level} · score {risk.score} (0–2 Low, 3–4 Medium, 5+ High)
          </div>
          {risk.points.map((p) => (
            <div key={p.factor}>
              +{p.points} {p.factor} <span className="text-slate-400">· {p.detail}</span>
            </div>
          ))}
          <div className="mt-1 text-slate-400">
            Confidence {risk.confidence}: {risk.confidence_basis}
          </div>
        </div>
      }
    >
      <Badge tone={RISK_TONE[risk.level]} dot className="cursor-help">
        {risk.level} risk
      </Badge>
    </Tip>
  )
}

/** The one panel: optional header (title, sub-line, right-hand actions). `flush` lets a table run edge to edge. */
export function Panel({ title, sub, actions, flush = false, children, className, id, testId }: { title?: ReactNode; sub?: ReactNode; actions?: ReactNode; flush?: boolean; children?: ReactNode; className?: string; id?: string; testId?: string }) {
  return (
    <section className={clsx('card min-w-0', flush && 'overflow-clip', className)} aria-labelledby={title ? id : undefined} data-testid={testId}>
      {(title || actions) && (
        <div className="panel-head">
          <div className="min-w-0">
            {title && (
              <h2 id={id} className="h-sec">
                {title}
              </h2>
            )}
            {sub && <p className="h-sub">{sub}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {flush ? children : <div className="p-4">{children}</div>}
    </section>
  )
}

/** The one chart container: titled panel, legend inside the chart, a deliberate empty state. */
export function ChartPanel({ title, sub, actions, children, empty, className, id }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; empty?: ReactNode; className?: string; id?: string }) {
  return (
    <Panel title={title} sub={sub} actions={actions} className={className} id={id}>
      {empty ? <ChartEmpty>{empty}</ChartEmpty> : children}
    </Panel>
  )
}

export function ChartEmpty({ children }: { children: ReactNode }) {
  return <div className="flex min-h-[160px] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/60 px-4 text-center text-sm text-slate-500">{children}</div>
}

/** Pill toggle group. Buttons keep their visible text as the accessible name. */
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Loading shows the shape of what is coming, not a lone spinner. */
export function Loading({ label = 'Loading…', block = false }: { label?: string; block?: boolean }) {
  if (block)
    return (
      <div role="status" aria-live="polite">
        <span className="sr-only">{label}</span>
        <div className="skeleton h-40 w-full" aria-hidden />
      </div>
    )
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="card mb-4 grid grid-cols-2 gap-px overflow-hidden bg-slate-200 md:grid-cols-4" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="space-y-2.5 bg-white p-4">
            <div className="skeleton h-3 w-20" />
            <div className="skeleton h-7 w-28" />
            <div className="skeleton h-3 w-32" />
          </div>
        ))}
      </div>
      <div className="card space-y-3 p-4" aria-hidden>
        <div className="skeleton h-4 w-40" />
        <div className="skeleton h-48 w-full" />
      </div>
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  const down = error instanceof ApiError && error.status === null
  const qc = useQueryClient()
  const Icon = down ? ServerOff : AlertCircle
  return (
    <div className="card flex flex-wrap items-start gap-3 border border-danger-600/30 bg-danger-50 p-4 text-sm text-danger-700" role="alert" data-testid="api-error">
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {down ? (
          <>
            <b>The backend isn't reachable.</b> Start the API on <code className="font-mono">localhost:8000</code> (or set <code className="font-mono">VITE_API_URL</code>) and reload.
          </>
        ) : (
          <>The backend returned an error: {String((error as Error)?.message ?? error)}</>
        )}
      </div>
      <button className="btn-outline btn-sm shrink-0 border-danger-600/30 text-danger-700 hover:border-danger-600 hover:text-danger-700" onClick={() => qc.invalidateQueries()}>
        <RefreshCw size={12} aria-hidden /> Try again
      </button>
    </div>
  )
}

export function Empty({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="px-4 py-12 text-center">
      <div className="text-sm font-medium text-slate-700">{children}</div>
      {hint && <div className="mx-auto mt-1 max-w-sm text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

/** A row of KPI cells in one panel: hairline dividers instead of a grid of separate cards. */
export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx('card mb-4 grid grid-cols-2 gap-px overflow-hidden bg-slate-200 max-md:[&>*:last-child:nth-child(odd)]:col-span-2', className)}>{children}</div>
}

export function Stat({ label, value, sub, how, tone, testId, lead = false, className }: { label: string; value: ReactNode; sub?: ReactNode; how?: ReactNode; tone?: 'save' | 'danger' | 'kept'; testId?: string; lead?: boolean; className?: string }) {
  const toneCls = tone === 'save' ? 'text-save-700' : tone === 'danger' ? 'text-danger-700' : tone === 'kept' ? 'text-kept-700' : 'text-slate-900'
  return (
    <div className={clsx('min-w-0 bg-white px-4 py-3.5', lead && 'max-md:col-span-2', className)}>
      <div className="label">{how ? <HowTip how={how}>{label}</HowTip> : label}</div>
      <div className={clsx('num mt-2 break-words font-semibold leading-none', lead ? 'text-[32px]' : 'text-xl md:text-2xl', toneCls)} style={{ letterSpacing: '-0.025em' }} data-testid={testId}>
        {value}
      </div>
      {sub && <div className="mt-2 text-xs leading-snug text-slate-600">{sub}</div>}
    </div>
  )
}

/** A supporting figure beside a hero number: label and value on one line, the working underneath. */
export function Fact({ label, value, sub, how, tone, testId }: { label: string; value: ReactNode; sub?: ReactNode; how?: ReactNode; tone?: 'save' | 'danger' | 'kept'; testId?: string }) {
  const toneCls = tone === 'save' ? 'text-save-700' : tone === 'danger' ? 'text-danger-700' : tone === 'kept' ? 'text-kept-700' : 'text-slate-900'
  return (
    <div className="px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="label">{how ? <HowTip how={how}>{label}</HowTip> : label}</div>
        <div className={clsx('num text-xl font-semibold leading-none', toneCls)} style={{ letterSpacing: '-0.02em' }} data-testid={testId}>
          {value}
        </div>
      </div>
      {sub && <div className="mt-1.5 text-xs text-slate-600">{sub}</div>}
    </div>
  )
}
