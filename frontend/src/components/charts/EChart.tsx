import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'

echarts.use([
  LineChart, BarChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  MarkLineComponent, MarkAreaComponent, VisualMapComponent, CanvasRenderer,
])

/** Thin ECharts wrapper: one instance per mount, resizes with its box, optional group for linked zoom. */
export function EChart({ option, height = 240, group, testId, ariaLabel, onClick }: { option: EChartsCoreOption; height?: number; group?: string; testId?: string; ariaLabel: string; onClick?: (params: { value?: unknown; dataIndex: number }) => void }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const clickRef = useRef(onClick)
  clickRef.current = onClick

  useEffect(() => {
    if (!el.current) return
    const c = echarts.init(el.current, undefined, { renderer: 'canvas' })
    chart.current = c
    c.on('click', (p) => clickRef.current?.(p as never))
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      c.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption({ useUTC: true, animation: false, ...option }, true)
  }, [option])

  useEffect(() => {
    if (!group || !chart.current) return
    chart.current.group = group
    echarts.connect(group)
  }, [group])

  return <div ref={el} style={{ height }} className="w-full" role="img" aria-label={ariaLabel} data-testid={testId} />
}
