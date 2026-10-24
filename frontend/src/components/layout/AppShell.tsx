import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { ResourceDrawer } from '../resource/ResourceDrawer'
import { PresetReconciler, Toaster } from './Toaster'
import { BackendWatcher } from './BackendWatcher'

export function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto" id="main">
          <Outlet />
        </main>
      </div>
      <ResourceDrawer />
      <Toaster />
      <PresetReconciler />
      <BackendWatcher />
    </div>
  )
}

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[1400px] px-6 py-5">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="page-sub">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}
