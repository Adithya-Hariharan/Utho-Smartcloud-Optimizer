import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import type { Forecast } from '../../types/api'
import { EChart } from './EChart'
import { INK, SERIES, axisCommon, baseGrid, tooltipBase } from './theme'
import { formatCompactINR, formatDayIST, formatINR } from '../../lib/format'

/**
 * Last 60 billed days, then the engine's 90-day forecast with its 95% band, and the same
 * forecast with the accepted actions applied (daily saving = accepted monthly saving × 24/730).
 */
export function ForecastChart({ forecast, acceptedMonthlySaving, height = 300 }: { forecast: Forecast; acceptedMonthlySaving: number; height?: number }) {
  const option = useMemo<EChartsCoreOption>(() => {
    const daily = (acceptedMonthlySaving * 24) / 730
    const dates = [...forecast.history.dates, ...forecast.forecast.dates]
    const pad = (n: number) => Array<number | null>(n).fill(null)
    const h = forecast.history.total.length
    const history = [...forecast.history.total, ...pad(forecast.forecast.dates.length)]
    const baseline = [...pad(h - 1), forecast.history.total[h - 1], ...forecast.forecast.baseline]
    const withActions = [...pad(h - 1), forecast.history.total[h - 1], ...forecast.forecast.baseline.map((v) => Math.round((v - daily) * 100) / 100)]
    const lower = [...pad(h), ...forecast.forecast.lower]
    const band = [...pad(h), ...forecast.forecast.upper.map((u, i) => Math.round((u - forecast.forecast.lower[i]) * 100) / 100)]
    return {
      grid: { ...baseGrid, left: 60, top: 32 },
      legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 2, textStyle: { color: INK.secondary, fontSize: 11 }, data: ['Billed', 'Forecast', 'With accepted actions', '95% band'] },
      tooltip: {
        ...tooltipBase,
        formatter: (ps: { axisValue: string; seriesName: string; value: number | null; marker: string }[]) =>
          [formatDayIST(ps[0].axisValue + 'T00:00:00+05:30'), ...ps.filter((p) => p.value !== null && p.seriesName !== 'band-base' && p.seriesName !== '95% band').map((p) => `${p.marker}${p.seriesName}: <b>${formatINR(p.value!)}</b>/day`)].join('<br/>'),
      },
      xAxis: { type: 'category', data: dates, boundaryGap: false, ...axisCommon, splitLine: { show: false }, axisLabel: { ...axisCommon.axisLabel, interval: 29, formatter: (d: string) => formatDayIST(d + 'T00:00:00+05:30') } },
      yAxis: { type: 'value', ...axisCommon, scale: true, axisLabel: { ...axisCommon.axisLabel, formatter: (v: number) => formatCompactINR(v) } },
      series: [
        { name: 'band-base', type: 'line', data: lower, stack: 'band', showSymbol: false, lineStyle: { opacity: 0 }, silent: true },
        { name: '95% band', type: 'line', data: band, stack: 'band', showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { color: SERIES[0], opacity: 0.12 }, itemStyle: { color: SERIES[0] }, silent: true },
        { name: 'Billed', type: 'line', data: history, showSymbol: false, lineStyle: { width: 1.5, color: INK.secondary }, itemStyle: { color: INK.secondary } },
        { name: 'Forecast', type: 'line', data: baseline, showSymbol: false, lineStyle: { width: 2, color: SERIES[0], type: 'dashed' }, itemStyle: { color: SERIES[0] } },
        { name: 'With accepted actions', type: 'line', data: withActions, showSymbol: false, lineStyle: { width: 2, color: SERIES[2] }, itemStyle: { color: SERIES[2] } },
      ],
    }
  }, [forecast, acceptedMonthlySaving])
  return <EChart option={option} height={height} testId="forecast-chart" ariaLabel="Bill forecast for the next 90 days, with and without accepted actions" />
}
