// Number and date formatting. Indian digit grouping everywhere (₹1,23,456); dates in IST.

const inrFmt = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

/** ₹1,23,456 · negative values as −₹1,152 */
export function formatINR(value: number): string {
  const v = Math.round(value)
  return `${v < 0 ? '−' : ''}₹${inrFmt.format(Math.abs(v))}`
}

/** Signed saving: +₹5,681 / −₹1,152 */
export function formatSignedINR(value: number): string {
  const v = Math.round(value)
  if (v === 0) return '₹0'
  return `${v > 0 ? '+' : '−'}₹${inrFmt.format(Math.abs(v))}`
}

/** Compact Indian units for KPI tiles: ₹6.57 L, ₹1.20 Cr, ₹48,200 */
export function formatCompactINR(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? '−' : ''
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`
  return `${sign}₹${inrFmt.format(Math.round(abs))}`
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}%`
}

export function formatNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value)
}

const IST = 'Asia/Kolkata'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const partsFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST, year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short',
})

/** Calendar parts of an instant in IST (locale-independent month names: en-IN would say "Sept"). */
export function istParts(t: string | number | Date) {
  const p = Object.fromEntries(partsFmt.formatToParts(new Date(t)).map((x) => [x.type, x.value]))
  return { year: +p.year, month: +p.month, day: +p.day, hour: +p.hour, minute: +p.minute, weekday: p.weekday as string }
}

/** 20 Sep 2026 */
export function formatDateIST(t: string | number): string {
  const p = istParts(t)
  return `${p.day} ${MONTHS[p.month - 1]} ${p.year}`
}

/** 20 Sep */
export function formatDayIST(t: string | number): string {
  const p = istParts(t)
  return `${p.day} ${MONTHS[p.month - 1]}`
}

/** 20 Sep, 14:05 IST */
export function formatDateTimeIST(t: string | number): string {
  const p = istParts(t)
  return `${p.day} ${MONTHS[p.month - 1]}, ${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')} IST`
}

/** Window like "20 Sep – 19 Oct 2026" (end is exclusive, so show the last included day) */
export function formatWindow(startIso: string, endIsoExclusive: string): string {
  const end = new Date(endIsoExclusive).getTime() - 60_000
  return `${formatDayIST(startIso)} – ${formatDateIST(end)}`
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return '—'
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
