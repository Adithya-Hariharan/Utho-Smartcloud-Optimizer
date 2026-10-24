import { NavLink } from 'react-router-dom'
import { Activity, BadgeIndianRupee, Bell, BookOpen, Cloud, DatabaseZap, LayoutDashboard, Leaf, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import clsx from 'clsx'
import { useAlerts, useAssumptions } from '../../api/data'
import { formatWindow } from '../../lib/format'
import { useUi, type Role } from '../../store/ui'

// Pages and the roles they are primarily for (PLAN §11).
export const NAV: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean; roles: Role[] }[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true, roles: ['leadership'] },
  { to: '/recommendations', label: 'Recommendations', icon: BadgeIndianRupee, roles: ['engineer'] },
  { to: '/kept', label: 'Checked & kept', icon: ShieldCheck, roles: ['engineer'] },
  { to: '/utilization', label: 'Utilization', icon: Activity, roles: ['engineer'] },
  { to: '/alerts', label: 'Alerts', icon: Bell, roles: ['engineer', 'leadership'] },
  { to: '/what-if', label: 'What-if', icon: SlidersHorizontal, roles: ['finance'] },
  { to: '/forecast', label: 'Forecast & Green', icon: Leaf, roles: ['finance', 'leadership'] },
  { to: '/data-quality', label: 'Data quality', icon: DatabaseZap, roles: ['engineer'] },
  { to: '/assumptions', label: 'Assumptions', icon: BookOpen, roles: ['finance'] },
]

export function Sidebar() {
  const meta = useAssumptions()
  const alerts = useAlerts()
  const critical = alerts.data?.items.filter((a) => a.severity === 'critical').length ?? 0
  const role = useUi((s) => s.role)
  const mine = NAV.filter((n) => n.roles.includes(role))
  const rest = NAV.filter((n) => !n.roles.includes(role))
  const link = (item: (typeof NAV)[number]) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end ?? false}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
          isActive ? 'bg-white/10 font-medium text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.06)]' : 'hover:bg-white/5 hover:text-white',
        )
      }
    >
      <item.icon size={16} />
      <span className="flex-1">{item.label}</span>
      {item.to === '/alerts' && critical > 0 && (
        <span className="rounded-full bg-danger-600 px-1.5 text-2xs font-semibold text-white" title={`${critical} critical alerts`}>
          {critical}
        </span>
      )}
    </NavLink>
  )

  return (
    <aside className="flex w-56 shrink-0 flex-col bg-brand-900 text-slate-300">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 text-sky-400">
          <Cloud size={18} strokeWidth={2.4} />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">SmartCloud</div>
          <div className="text-2xs text-slate-400">Optimizer</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-2" aria-label="Main">
        <div className="px-3 pb-1 pt-1 text-2xs font-semibold uppercase tracking-wide text-slate-500" data-testid="nav-for-you">For you</div>
        {mine.map(link)}
        <div className="px-3 pb-1 pt-3 text-2xs font-semibold uppercase tracking-wide text-slate-500">More</div>
        {rest.map(link)}
      </nav>
      <div className="space-y-1 border-t border-white/10 px-4 py-3 text-2xs text-slate-400" data-testid="data-window">
        {meta.data && (
          <div>
            Data: <span className="text-slate-200">{formatWindow(meta.data.data_window.start, meta.data.data_window.end)}</span>
          </div>
        )}
      </div>
    </aside>
  )
}
