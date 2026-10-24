import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { ResourceDrawer } from '../resource/ResourceDrawer'
import { PresetReconciler, Toaster } from './Toaster'
import { BackendWatcher } from './BackendWatcher'

export function AppShell() {
  const [navOpen, setNavOpen] = useState(false)
  const { pathname } = useLocation()

  // the off-canvas menu (below lg) closes when you navigate or press Escape
  useEffect(() => setNavOpen(false), [pathname])
  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setNavOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen])

  return (
    <div className="flex h-screen overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[120] focus:rounded-full focus:bg-brand focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white">
        Skip to content
      </a>
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header onMenu={() => setNavOpen(true)} menuOpen={navOpen} />
        <main className="flex-1 overflow-y-auto" id="main" tabIndex={-1}>
          <div key={pathname} className="animate-rise-in">
            <Outlet />
          </div>
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
    <div className="mx-auto max-w-[1400px] px-4 pb-10 pt-5 sm:px-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="page-sub">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}
