// The what-if itself runs on the backend (POST /api/whatif). This only draws the policy the
// user is typing as a 7 × 24 grid, which is a function of the form inputs alone.

/** 168 booleans, index = day × 24 + hour (Monday first), true = scheduled off. */
export interface OffPolicy { start: number; end: number; weekends: boolean }

/** "20:00-08:00" as sent to POST /api/whatif (PLAN §10) */
export const offString = (start: number, end: number) => `${String(start).padStart(2, '0')}:00-${String(end).padStart(2, '0')}:00`

export function offMask({ start, end, weekends }: OffPolicy): boolean[] {
  return Array.from({ length: 168 }, (_, i) => {
    const d = Math.floor(i / 24), h = i % 24
    if (weekends && d >= 5) return true
    if (start === end) return false
    return start < end ? h >= start && h < end : h >= start || h < end
  })
}
