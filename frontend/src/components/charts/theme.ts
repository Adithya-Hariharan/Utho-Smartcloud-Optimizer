// Chart tokens (dataviz reference palette, light mode). Categorical slots are used in this
// fixed order and follow the entity, never its rank. Status colours are reserved for
// thresholds/alerts and always come with a label.
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'] as const
export const SEQ_BLUE = ['#f1f5fb', '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'] as const
export const STATUS = { good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b' } as const
export const INK = { primary: '#171717', secondary: '#4d4d4d', muted: '#a1a1a1', grid: '#ededed', axis: '#d4d4d4', surface: '#ffffff' } as const
/** actual (observed) vs projected in Peak Replay */
export const ACTUAL = '#a1a1a1'
export const PROJECTED = SERIES[0]

/** Fixed colour per environment, so filters never repaint survivors. */
export const ENV_COLOR: Record<string, string> = { prod: SERIES[0], staging: SERIES[1], dev: SERIES[2], untagged: SERIES[3] }

export const IST_OFFSET_MS = 5.5 * 3600 * 1000
/** Shift an instant so ECharts (useUTC: true) labels it in IST on any machine. */
export const toIstEpoch = (t: string | number) => (typeof t === 'number' ? t : Date.parse(t)) + IST_OFFSET_MS

const pad = (n: number) => String(n).padStart(2, '0')
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** Format an IST-shifted epoch (see toIstEpoch). */
export function fmtIst(shifted: number, withTime = true) {
  const d = new Date(shifted)
  const day = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
  return withTime ? `${day}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} IST` : day
}

export const FONT = "Inter, ui-sans-serif, system-ui, 'Segoe UI', sans-serif"

export const baseGrid = { left: 44, right: 16, top: 28, bottom: 28, containLabel: false }

export const axisCommon = {
  axisLine: { lineStyle: { color: INK.axis } },
  axisTick: { show: false },
  axisLabel: { color: INK.secondary, fontSize: 11, fontFamily: FONT },
  splitLine: { lineStyle: { color: INK.grid } },
}

export const timeAxis = {
  type: 'time' as const,
  ...axisCommon,
  splitLine: { show: false },
  axisLabel: {
    color: INK.secondary,
    fontSize: 11,
    fontFamily: FONT,
    hideOverlap: true,
    formatter: (v: number) => {
      const d = new Date(v)
      return d.getUTCHours() === 0 && d.getUTCMinutes() === 0 ? fmtIst(v, false) : `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
    },
  },
}

export const tooltipBase = {
  trigger: 'axis' as const,
  backgroundColor: '#171717',
  borderWidth: 0,
  padding: [8, 10],
  textStyle: { color: '#fafafa', fontSize: 12, fontFamily: FONT, lineHeight: 18 },
  extraCssText: 'border-radius:6px;box-shadow:0 8px 16px -4px rgba(0,0,0,.2),0 2px 2px rgba(0,0,0,.08);font-variant-numeric:tabular-nums;',
  axisPointer: { type: 'line' as const, lineStyle: { color: INK.muted, type: 'dashed' as const } },
}
