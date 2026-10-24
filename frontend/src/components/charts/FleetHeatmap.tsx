import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import type { ResourceRow } from '../../types/contract'
import { EChart } from './EChart'
import { INK, SEQ_BLUE, tooltipBase } from './theme'
import { formatDayIST } from '../../lib/format'

/** Resources × days, cell = daily p95 CPU (IST days). Sequential single hue; empty = no data. */
export function FleetHeatmap({ rows, start, onPick }: { rows: ResourceRow[]; start: string; onPick: (id: string) => void }) {
  const option = useMemo<EChartsCoreOption>(() => {
    const days = Array.from({ length: 30 }, (_, d) => formatDayIST(Date.parse(start) + d * 86_400_000))
    const names = rows.map((r) => r.name)
    const data: [number, number, number | string][] = []
    rows.forEach((r, y) => r.daily_p95?.forEach((v, x) => data.push([x, y, v ?? '-'])))
    return {
      grid: { left: 130, right: 16, top: 8, bottom: 56 },
      tooltip: {
        ...tooltipBase,
        trigger: 'item',
        formatter: (p: { value: [number, number, number | string] }) => `${names[p.value[1]]}<br/>${days[p.value[0]]}: daily p95 CPU <b>${p.value[2] === '-' ? 'no data' : `${p.value[2]}%`}</b>`,
      },
      xAxis: { type: 'category', data: days, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: INK.secondary, fontSize: 10, interval: 4 } },
      yAxis: { type: 'category', data: names, inverse: true, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: INK.secondary, fontSize: 9, interval: 0 } },
      visualMap: { min: 0, max: 100, orient: 'horizontal', left: 'center', bottom: 4, itemHeight: 160, itemWidth: 10, text: ['100%', '0%'], textStyle: { color: INK.secondary, fontSize: 10 }, inRange: { color: [...SEQ_BLUE] } },
      series: [{ type: 'heatmap', data, itemStyle: { borderColor: '#fff', borderWidth: 0.5 } }],
    }
  }, [rows, start])
  return (
    <EChart
      option={option}
      height={Math.max(260, rows.length * 11 + 70)}
      testId="fleet-heatmap"
      ariaLabel="Daily p95 CPU per VM over 30 days"
      onClick={(p) => {
        const v = p.value as [number, number] | undefined
        if (v) onPick(rows[v[1]].resource_id)
      }}
    />
  )
}
