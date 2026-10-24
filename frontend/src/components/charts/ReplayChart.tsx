import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import type { ReplaySeries } from '../../types/api'
import { EChart } from './EChart'
import { ACTUAL, INK, PROJECTED, STATUS, axisCommon, baseGrid, fmtIst, timeAxis, toIstEpoch, tooltipBase } from './theme'

/**
 * Peak Replay, as computed by the engine: observed CPU on the current plan vs the same
 * demand projected onto the target plan. Projected values may exceed 100%: demand the
 * smaller machine could not serve. Segments above 90% are drawn red.
 */
export function ReplayChart({ replay, height = 230 }: { replay: ReplaySeries; height?: number }) {
  const option = useMemo<EChartsCoreOption>(() => {
    const t0 = toIstEpoch(replay.start)
    const step = replay.step_seconds * 1000
    const at = (i: number) => t0 + i * step
    const actual = replay.actual_cpu.map((v, i) => [at(i), v])
    const projected = replay.projected_cpu.map((v, i) => [at(i), v])
    const above = (j: number) => (replay.projected_cpu[j] ?? 0) > 90
    // red overlay only where projected demand breaches 90% (null elsewhere)
    const over = replay.projected_cpu.map((v, i) => [at(i), v !== null && (v > 90 || above(i - 1) || above(i + 1)) ? v : null])
    return {
      grid: { ...baseGrid, top: 30, bottom: 52 },
      legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 2, textStyle: { color: INK.secondary, fontSize: 11 } },
      tooltip: {
        ...tooltipBase,
        formatter: (ps: { value: [number, number | null]; seriesName: string; marker: string }[]) =>
          [fmtIst(ps[0].value[0]), ...ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.value[1] ?? 'no data'}${p.value[1] === null ? '' : '%'}</b>`)].join('<br/>'),
      },
      xAxis: timeAxis,
      yAxis: { type: 'value', ...axisCommon, axisLabel: { ...axisCommon.axisLabel, formatter: '{value}%' } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8, borderColor: INK.grid, showDetail: false }],
      series: [
        { name: `Actual on ${replay.from_plan} (${replay.from_vcpu} vCPU)`, type: 'line', data: actual, showSymbol: false, connectNulls: false, lineStyle: { width: 1.25, color: ACTUAL }, itemStyle: { color: ACTUAL } },
        {
          name: `Projected on ${replay.to_plan} (${replay.to_vcpu} vCPU)`,
          type: 'line',
          data: projected,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1.5, color: PROJECTED },
          itemStyle: { color: PROJECTED },
          markLine: {
            symbol: 'none',
            silent: true,
            lineStyle: { color: STATUS.critical, type: 'dashed', width: 1.5 },
            label: { formatter: '90% limit', color: STATUS.critical, fontSize: 10, position: 'insideEndTop' },
            data: [{ yAxis: 90 }],
          },
        },
        { name: 'Above 90% (would be slow)', type: 'line', data: over, showSymbol: false, connectNulls: false, lineStyle: { width: 2, color: STATUS.critical }, itemStyle: { color: STATUS.critical }, z: 3 },
      ],
    }
  }, [replay])

  return <EChart option={option} height={height} testId="replay-chart" ariaLabel={`Peak Replay: actual CPU on ${replay.from_plan} versus projected on ${replay.to_plan}`} />
}
