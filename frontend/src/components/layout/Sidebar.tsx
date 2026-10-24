import { NavLink } from 'react-router-dom'
import { Activity, BadgeIndianRupee, Bell, BookOpen, Cloud, DatabaseZap, LayoutDashboard, Leaf, ShieldCheck, SlidersHorizontal, X } from 'lucide-react'
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

/** Fixed rail from lg up; an off-canvas menu below it. */
export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
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
          'group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors duration-150',
          isActive ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
        )
      }
    >
      {({ isActive }) => (
        <>
          <item.icon size={16} className={clsx('shrink-0 transition-colors duration-150', isActive ? 'text-slate-900' : 'text-slate-500 group-hover:text-slate-800')} aria-hidden />
          <span className="flex-1 truncate">{item.label}</span>
          {item.to === '/alerts' && critical > 0 && (
            <span className="num rounded-full bg-danger-600 px-1.5 text-xs font-semibold text-white" title={`${critical} critical alerts`}>
              {critical}
            </span>
          )}
        </>
      )}
    </NavLink>
  )

  return (
    <>
      <div className={clsx('fixed inset-0 z-40 bg-slate-900/40 transition-opacity duration-200 lg:hidden', open ? 'opacity-100' : 'pointer-events-none opacity-0')} onClick={onClose} aria-hidden />
      <aside
        id="sidebar"
        className={clsx(
          'z-50 flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white text-slate-600 transition-[transform,visibility] duration-200 ease-out max-lg:fixed max-lg:inset-y-0 max-lg:left-0 lg:w-56',
          open ? 'max-lg:visible max-lg:translate-x-0' : 'max-lg:invisible max-lg:-translate-x-full',
        )}
      >
        <div className="flex items-center gap-2.5 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-brand text-on-brand">
            <Cloud size={18} strokeWidth={2.4} aria-hidden />
          </div>
          <div className="flex-1 leading-tight">
            <div className="text-sm font-semibold text-slate-900">SmartCloud</div>
            <div className="text-xs text-slate-500">Optimizer</div>
          </div>
          <button className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900 lg:hidden" onClick={onClose} aria-label="Close navigation">
            <X size={16} />
          </button>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2" aria-label="Main">
          <div className="px-2.5 pb-1 pt-1 text-xs font-medium text-slate-500" data-testid="nav-for-you">For you</div>
          {mine.map(link)}
          <div className="px-2.5 pb-1 pt-5 text-xs font-medium text-slate-500">More</div>
          {rest.map(link)}
        </nav>
        <div className="space-y-1 border-t border-slate-200 px-4 py-3 text-xs text-slate-500" data-testid="data-window">
          {meta.data && (
            <div>
              Data: <span className="font-medium text-slate-700">{formatWindow(meta.data.data_window.start, meta.data.data_window.end)}</span>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
