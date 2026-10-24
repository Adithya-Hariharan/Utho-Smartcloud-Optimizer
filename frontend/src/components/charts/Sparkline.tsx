/** Plain-SVG sparkline (no chart instance per table row). Nulls break the line; the max is marked. */
export function Sparkline({ values, width = 120, height = 28, color = '#2a78d6', max = 100, threshold, label }: { values: (number | null)[]; width?: number; height?: number; color?: string; max?: number; threshold?: number; label: string }) {
  const n = values.length
  if (!n) return null
  const x = (i: number) => (i / Math.max(n - 1, 1)) * (width - 4) + 2
  const y = (v: number) => height - 2 - (Math.min(v, max) / max) * (height - 4)
  const segments: string[] = []
  let cur: string[] = []
  values.forEach((v, i) => {
    if (v === null) {
      if (cur.length) segments.push(cur.join(' '))
      cur = []
    } else cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`)
  })
  if (cur.length) segments.push(cur.join(' '))
  let peak = -1
  values.forEach((v, i) => {
    if (v !== null && (peak < 0 || v > (values[peak] ?? -1))) peak = i
  })
  return (
    <svg width={width} height={height} role="img" aria-label={label} className="overflow-visible">
      <title>{label}</title>
      {threshold !== undefined && <line x1={0} x2={width} y1={y(threshold)} y2={y(threshold)} stroke="#d03b3b" strokeDasharray="3 3" strokeWidth={1} opacity={0.6} />}
      {segments.map((pts, i) => (
        <polyline key={i} points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {peak >= 0 && values[peak] !== null && <circle cx={x(peak)} cy={y(values[peak]!)} r={2.5} fill={color} stroke="#fff" strokeWidth={1} />}
    </svg>
  )
}
