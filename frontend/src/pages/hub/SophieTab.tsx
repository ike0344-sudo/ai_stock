import { useHub } from '@/api/hub'
import { HubGate } from '@/components/hub/HubGate'
import { SophiePanel } from '@/components/hub/sophie/SophiePanel'
import type { SophieData } from '@/types/data'

export function SophieTab() {
  const q = useHub<SophieData>('/api/data/sophie', { refetchMs: 30_000 })
  return <HubGate query={q} path="/api/data/sophie">{(d) => <SophiePanel d={d} />}</HubGate>
}
