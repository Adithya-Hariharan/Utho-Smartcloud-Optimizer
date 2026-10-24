import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { Info, Loader2 } from 'lucide-react'
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
      className="pointer-events-none fixed z-[100] max-w-sm rounded-lg bg-brand-900 px-3 py-2 text-xs leading-relaxed text-slate-100 shadow-pop"
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

export function VerdictBadge({ verdict, label }: { verdict: Verdict; label?: string }) {
  const m = VERDICT_META[verdict]
  return (
    <span className={clsx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-semibold ring-1 ring-inset', m.cls)}>
      <span className={clsx('h-1.5 w-1.5 rounded-full', m.dot)} />
      {label ?? m.label}
    </span>
  )
}

const RISK_CLS = {
  Low: 'bg-save-50 text-save-700 ring-save-600/25',
  Medium: 'bg-review-50 text-review-700 ring-review-600/25',
  High: 'bg-danger-50 text-danger-700 ring-danger-600/25',
}

export function RiskChip({ risk }: { risk: Risk | null }) {
  if (!risk) return <span className="text-slate-400">—</span>
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
      <span className={clsx('inline-flex cursor-help items-center whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-semibold ring-1 ring-inset', RISK_CLS[risk.level])}>
        {risk.level} risk
      </span>
    </Tip>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 size={16} className="animate-spin" /> {label}
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  const down = error instanceof ApiError && error.status === null
  return (
    <div className="card card-pad border-danger-600/30 bg-danger-50 text-sm text-danger-700" role="alert" data-testid="api-error">
      {down ? (
        <>
          <b>The backend isn't reachable.</b> Start the API on <code className="font-mono">localhost:8000</code> (or set <code className="font-mono">VITE_API_URL</code>) and reload.
        </>
      ) : (
        <>The backend returned an error: {String((error as Error)?.message ?? error)}</>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-slate-500">{children}</div>
}

export function Stat({ label, value, sub, how, tone, testId }: { label: string; value: ReactNode; sub?: ReactNode; how?: ReactNode; tone?: 'save' | 'danger' | 'kept'; testId?: string }) {
  const toneCls = tone === 'save' ? 'text-save-700' : tone === 'danger' ? 'text-danger-700' : tone === 'kept' ? 'text-kept-700' : 'text-slate-900'
  return (
    <div className="card card-pad">
      <div className="label">{how ? <HowTip how={how}>{label}</HowTip> : label}</div>
      <div className={clsx('num mt-1 text-2xl font-normal tracking-tight', toneCls)} data-testid={testId}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}
