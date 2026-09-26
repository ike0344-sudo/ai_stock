// echarts 래퍼 — option 만 넘기면 된다. 필요한 차트·컴포넌트만 등록해 번들을 줄인다(트리 셰이킹).
// 캔들·곡선·히트맵·막대(설계서 §5.3) 가 여기서 필요로 하는 것들.
import { BarChart, CandlestickChart, HeatmapChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import { useDark } from '@/lib/theme'

echarts.use([
  BarChart, CandlestickChart, HeatmapChart, LineChart, ScatterChart,
  DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent, TitleComponent, TooltipComponent,
  VisualMapComponent, CanvasRenderer,
])

export type EChartOption = echarts.EChartsCoreOption

interface Props {
  option: EChartOption
  height?: number | string
  /** true 면 옵션을 합쳐 갱신한다(series id 가 같으면 값이 바뀔 때 부드럽게 이어져 곡선이 자라는 모습이 나온다). 기본은 통째 교체 */
  merge?: boolean
}

export function EChart({ option, height = 320, merge = false }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const { dark } = useDark()

  // 테마가 바뀌면 인스턴스를 새로 만든다(echarts 는 init 시점에 테마를 고른다)
  useEffect(() => {
    if (!el.current) return
    const c = echarts.init(el.current, dark ? 'dark' : undefined)
    chart.current = c
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      c.dispose()
      chart.current = null
    }
  }, [dark])

  useEffect(() => {
    // 다크에서는 echarts 기본 배경이 흰색이라 투명으로 — 카드 배경이 비쳐 보이게
    chart.current?.setOption({ backgroundColor: 'transparent', ...option }, !merge)
  }, [option, dark, merge])

  return <div ref={el} style={{ width: '100%', height }} />
}
