import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import type { MetricSeries, MetricStats } from '../../types/contract'
import { EChart } from './EChart'
import { INK, SERIES, STATUS, axisCommon, baseGrid, fmtIst, timeAxis, toIstEpoch, tooltipBase } from './theme'

export interface Band { start: string; end: string; label: string; tone?: 'gap' | 'alert' }

/**
 * One metric over the window. Hourly data carries mean + max: the max is drawn as a light
 * band edge so short peaks (a 40-minute 02:00 batch) never disappear into an average.
 * Missing data stays a gap (null), never 0, and is shaded with its reason. Optional dotted
 * p50 / p95 / p99 lines come from the engine's evidence for the same metric.
 */
export function TimeSeriesChart({
  series, label, unit = '%', color = SERIES[0], threshold, percentiles, bands = [], height = 200, group, testId, zoom = false, yMax,
}: {
  series: MetricSeries
  label: string
  unit?: string
  color?: string
  threshold?: { value: number; label: string }
  percentiles?: Pick<MetricStats, 'p50' | 'p95' | 'p99'> | null
  bands?: Band[]
  height?: number
  group?: string
  testId?: string
  zoom?: boolean
  yMax?: number
}) {
  const option = useMemo<EChartsCoreOption>(() => {
    const t0 = toIstEpoch(series.start)
    const step = series.step_seconds * 1000
    const fine = series.step_seconds < 3600
    const mean = series.mean.map((v, i) => [t0 + i * step, v])
    const max = series.max.map((v, i) => [t0 + i * step, v])
    const allBands = [
      ...series.gaps.map((g) => ({ start: g.start, end: g.end, label: g.kind === 'flatline' ? `stuck agent (${g.hours} h): treated as missing` : `no data (${g.hours} h)`, tone: 'gap' as const })),
      ...bands,
    ]
    const lines: object[] = []
    if (threshold) lines.push({ yAxis: threshold.value, lineStyle: { color: STATUS.critical, type: 'dashed', width: 1.5 }, label: { formatter: threshold.label, color: STATUS.critical } })
    if (percentiles)
      for (const [k, v] of [['p50', percentiles.p50], ['p95', percentiles.p95], ['p99', percentiles.p99]] as const)
        // unlabelled on the chart (close values would collide); the values are printed under the chart title
        lines.push({ yAxis: v, name: k, lineStyle: { color: INK.secondary, type: 'dotted', width: 1 }, label: { show: false } })
    const word = fine ? '5-min' : 'hourly'
    return {
      grid: { ...baseGrid, right: 40, bottom: zoom ? 56 : 28 },
      tooltip: {
        ...tooltipBase,
        formatter: (ps: { value: [number, number | null]; seriesName: string; marker: string }[]) => {
          const head = fmtIst(ps[0].value[0])
          return [head, ...ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.value[1] === null ? 'no data' : `${p.value[1]}${unit}`}</b>`)].join('<br/>')
        },
      },
      legend: fine ? undefined : { top: 0, right: 0, itemWidth: 14, itemHeight: 2, textStyle: { color: INK.secondary, fontSize: 11 }, data: [`${label} ${word} max`, `${label} ${word} mean`] },
      xAxis: timeAxis,
      yAxis: { type: 'value', ...axisCommon, max: yMax, axisLabel: { ...axisCommon.axisLabel, formatter: `{value}${unit === '%' ? '%' : ''}` } },
      dataZoom: zoom ? [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8, borderColor: INK.grid, showDetail: false }] : [{ type: 'inside' }],
      series: [
        ...(fine
          ? []
          : [{ name: `${label} ${word} max`, type: 'line', data: max, showSymbol: false, connectNulls: false, lineStyle: { width: 1, color, opacity: 0.45 }, itemStyle: { color }, areaStyle: { color, opacity: 0.08 } }]),
        {
          name: fine ? `${label} (5-min)` : `${label} ${word} mean`,
          type: 'line',
          data: mean,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: fine ? 1.25 : 2, color },
          itemStyle: { color },
          markLine: lines.length ? { symbol: 'none', silent: true, label: { fontSize: 10, position: 'end' }, data: lines } : undefined,
          markArea: allBands.length
            ? {
                silent: false,
                data: allBands.map((b) => [
                  { xAxis: toIstEpoch(b.start), name: b.label, itemStyle: { color: b.tone === 'alert' ? 'rgba(208,59,59,0.10)' : 'rgba(100,116,139,0.16)' }, label: { show: false } },
                  { xAxis: toIstEpoch(b.end) },
                ]),
                tooltip: { show: true, formatter: (p: { name: string }) => p.name },
              }
            : undefined,
        },
      ],
    }
  }, [series, label, unit, color, threshold, percentiles, bands, zoom, yMax])

  return <EChart option={option} height={height} group={group} testId={testId} ariaLabel={`${label} over 30 days`} />
}
