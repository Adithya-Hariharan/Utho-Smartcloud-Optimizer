import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import Alerts from './pages/Alerts'
import Assumptions from './pages/Assumptions'
import DataQuality from './pages/DataQuality'
import Forecast from './pages/Forecast'
import Kept from './pages/Kept'
import Overview from './pages/Overview'
import Recommendations from './pages/Recommendations'
import ResourceDetail from './pages/ResourceDetail'
import Utilization from './pages/Utilization'
import WhatIf from './pages/WhatIf'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="recommendations" element={<Recommendations />} />
        <Route path="kept" element={<Kept />} />
        <Route path="utilization" element={<Utilization />} />
        <Route path="utilization/:id" element={<ResourceDetail />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="what-if" element={<WhatIf />} />
        <Route path="forecast" element={<Forecast />} />
        <Route path="data-quality" element={<DataQuality />} />
        <Route path="assumptions" element={<Assumptions />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
