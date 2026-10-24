import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import type { Summary } from '../../types/api'
import { EChart } from './EChart'
import { ENV_COLOR, INK, SERIES, axisCommon, baseGrid, tooltipBase } from './theme'
import { formatCompactINR, formatDayIST, formatINR, titleCase } from '../../lib/format'

const ENV_ORDER = ['prod', 'staging', 'dev', 'untagged']

/** Daily billed cost stacked by environment, 180 days. Fixed colour per env. */
export function BillTrendChart({ trend, height = 260 }: { trend: Summary['bill_trend_6m']; height?: number }) {
  const option = useMemo<EChartsCoreOption>(() => {
    const billing = trend
    const envs = ENV_ORDER.filter((e) => billing.by_env[e])
    return {
      grid: { ...baseGrid, left: 56, top: 32 },
      legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: INK.secondary, fontSize: 11 }, data: envs.map(titleCase) },
      tooltip: {
        ...tooltipBase,
        formatter: (ps: { axisValue: string; seriesName: string; value: number; marker: string }[]) => {
          const total = ps.reduce((s, p) => s + p.value, 0)
          return [`${ps[0].axisValue}: <b>${formatINR(total)}</b>/day`, ...[...ps].reverse().map((p) => `${p.marker}${p.seriesName}: ${formatINR(p.value)}`)].join('<br/>')
        },
      },
      xAxis: { type: 'category', data: billing.dates, boundaryGap: false, ...axisCommon, splitLine: { show: false }, axisLabel: { ...axisCommon.axisLabel, interval: 29, formatter: (d: string) => formatDayIST(d + 'T00:00:00+05:30') } },
      yAxis: { type: 'value', ...axisCommon, axisLabel: { ...axisCommon.axisLabel, formatter: (v: number) => formatCompactINR(v) } },
      series: envs.map((e) => ({
        name: titleCase(e),
        type: 'line',
        stack: 'bill',
        data: billing.by_env[e],
        showSymbol: false,
        lineStyle: { width: 1, color: ENV_COLOR[e] },
        itemStyle: { color: ENV_COLOR[e] },
        areaStyle: { color: ENV_COLOR[e], opacity: 0.55 },
      })),
    }
  }, [trend])
  return <EChart option={option} height={height} testId="bill-trend" ariaLabel="Daily cost by environment over 180 days" />
}

/**
 * First 30 billed days → change per category → last 30 billed days, drawn horizontally so
 * every category name and value has room (8 teams don't fit side by side in a narrow card).
 * Totals are slate; each category keeps its entity colour; values are direct-labelled.
 */
export type WaterfallBy = 'env' | 'team' | 'age'
const AGE_COLOR: Record<string, string> = { 'new resources': SERIES[1], 'existing resources': SERIES[0] }

export function GrowthWaterfall({ growth, by }: { growth: Summary['growth_waterfall']; by: WaterfallBy }) {
  const { option, height } = useMemo(() => {
    const rows = by === 'env' ? growth.by_env : by === 'team' ? growth.by_team : growth.by_age
    const teamOrder = growth.by_team.map((t) => t.key).sort()
    const color = (k: string) => (by === 'env' ? ENV_COLOR[k] ?? SERIES[7] : by === 'age' ? AGE_COLOR[k] ?? SERIES[7] : SERIES[teamOrder.indexOf(k) % SERIES.length])
    const deltas = rows.filter((x) => x.delta_inr !== 0).map((x) => ({ k: x.key, d: x.delta_inr }))
    const billing = { first30: { total: growth.first30.total_inr }, last30: { total: growth.last30.total_inr } }
    const cats = ['First 30 days', ...deltas.map((x) => titleCase(x.k)), 'Last 30 days']
    let run = billing.first30.total
    const base: number[] = [0]
    const val: { value: number; itemStyle: { color: string } }[] = [{ value: billing.first30.total, itemStyle: { color: '#64748b' } }]
    for (const x of deltas) {
      base.push(x.d >= 0 ? run : run + x.d)
      val.push({ value: Math.abs(x.d), itemStyle: { color: color(x.k) } })
      run += x.d
    }
    base.push(0)
    val.push({ value: billing.last30.total, itemStyle: { color: '#334155' } })
    const signed = [billing.first30.total, ...deltas.map((x) => x.d), billing.last30.total]
    const isTotal = (i: number) => i === 0 || i === cats.length - 1
    const min = Math.floor((billing.first30.total * 0.85) / 50000) * 50000
    const option: EChartsCoreOption = {
      grid: { left: 96, right: 78, top: 8, bottom: 28 },
      tooltip: {
        ...tooltipBase,
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0].dataIndex
          const v = signed[i]
          return isTotal(i)
            ? `${cats[i]}: <b>${formatINR(v)}</b> billed`
            : `${cats[i]}: <b>${v > 0 ? '+' : '−'}${formatINR(Math.abs(v))}</b> (${((v / billing.first30.total) * 100).toFixed(1)} pts of the growth)`
        },
      },
      xAxis: {
        type: 'value',
        ...axisCommon,
        min,
        splitNumber: 3,
        axisLabel: { ...axisCommon.axisLabel, formatter: (v: number) => formatCompactINR(v) },
      },
      yAxis: {
        type: 'category',
        data: cats,
        inverse: true,
        ...axisCommon,
        splitLine: { show: false },
        axisLabel: { ...axisCommon.axisLabel, fontSize: 11, color: INK.secondary, fontWeight: 500 },
      },
      series: [
        { type: 'bar', stack: 'w', data: base, itemStyle: { color: 'transparent' }, emphasis: { disabled: true }, silent: true },
        {
          type: 'bar',
          stack: 'w',
          data: val,
          barWidth: '62%',
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: 'right',
            distance: 6,
            color: INK.primary,
            fontSize: 11,
            fontWeight: 600,
            formatter: (p: { dataIndex: number }) => {
              const v = signed[p.dataIndex]
              return isTotal(p.dataIndex) ? formatCompactINR(v) : `${v > 0 ? '+' : '−'}${formatINR(Math.abs(v))}`
            },
          },
        },
      ],
    }
    return { option, height: Math.max(270, cats.length * 32 + 40) }
  }, [growth, by])
  return <EChart option={option} height={height} testId="growth-waterfall" ariaLabel={`Bill growth by ${by}: first 30 days to last 30 days`} />
}
