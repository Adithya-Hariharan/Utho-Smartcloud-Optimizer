import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import { EChart } from './EChart'
import { INK, SEQ_BLUE, tooltipBase } from './theme'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}`)

/** 7 × 24 p95 CPU in IST (index = day × 24 + hour, Monday first). Sequential single hue. */
export function HourOfWeekHeatmap({ values, height = 200, label = 'p95 CPU', testId = 'how-heatmap', marks }: { values: (number | null)[]; height?: number; label?: string; testId?: string; marks?: Set<number> }) {
  const option = useMemo<EChartsCoreOption>(() => {
    const data = values.map((v, i) => [i % 24, i >= 0 ? 6 - Math.floor(i / 24) : 0, v ?? '-'])
    return {
      grid: { left: 40, right: 12, top: 8, bottom: 44 },
      tooltip: {
        ...tooltipBase,
        trigger: 'item',
        formatter: (p: { value: [number, number, number | string] }) => {
          const [h, d, v] = p.value
          const idx = (6 - d) * 24 + h
          return `${DAYS[6 - d]} ${HOURS[h]}:00–${HOURS[(h + 1) % 24]}:00 IST<br/>${label}: <b>${v === '-' ? 'no data' : `${v}%`}</b>${marks?.has(idx) ? '<br/>scheduled off' : ''}`
        },
      },
      xAxis: { type: 'category', data: HOURS, splitArea: { show: false }, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: INK.secondary, fontSize: 10, interval: 2 } },
      yAxis: { type: 'category', data: [...DAYS].reverse(), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: INK.secondary, fontSize: 10 } },
      visualMap: {
        min: 0, max: 100, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 120, itemWidth: 10,
        text: ['100%', '0%'], textStyle: { color: INK.secondary, fontSize: 10 }, inRange: { color: [...SEQ_BLUE] },
      },
      series: [{ type: 'heatmap', data, itemStyle: { borderColor: '#fff', borderWidth: 1 }, emphasis: { itemStyle: { borderColor: INK.primary, borderWidth: 1 } } }],
    }
  }, [values, label, marks])
  return <EChart option={option} height={height} testId={testId} ariaLabel={`${label} by hour of week (IST)`} />
}
