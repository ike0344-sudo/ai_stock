import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { BacktestPage } from '@/pages/BacktestPage'
import { HubPage } from '@/pages/HubPage'
import { OptimizePage } from '@/pages/OptimizePage'
import { ComparePage } from '@/pages/ComparePage'
import { ResultPage } from '@/pages/ResultPage'
import { RunsPage } from '@/pages/RunsPage'

// 경로 (설계서 §5.4): #/hub/{overview,collect,schedules,ledger,quality,sophie} · #/backtest · #/results/:runId
//                     · #/optimize · #/runs · #/compare?ids=  — 뒤 셋은 해당 모듈에서 추가
export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/hub/overview" replace />} />
        <Route path="hub" element={<HubPage />} />
        <Route path="hub/:tab" element={<HubPage />} />
        <Route path="backtest" element={<BacktestPage />} />
        <Route path="optimize" element={<OptimizePage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="results/:runId" element={<ResultPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="*" element={<Navigate to="/hub/overview" replace />} />
      </Route>
    </Routes>
  )
}
