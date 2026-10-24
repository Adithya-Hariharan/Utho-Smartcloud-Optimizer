import { describe, expect, it } from 'vitest'
import { formatCompactINR, formatDateTimeIST, formatINR, formatPct, formatSignedINR, formatWindow, istParts } from './format'

describe('INR', () => {
  it('uses Indian digit grouping', () => {
    expect(formatINR(123456)).toBe('₹1,23,456')
    expect(formatINR(6573030)).toBe('₹65,73,030')
    expect(formatINR(705)).toBe('₹705')
    expect(formatINR(-1152)).toBe('−₹1,152')
  })
  it('signs savings and compacts KPIs in lakh / crore', () => {
    expect(formatSignedINR(5681)).toBe('+₹5,681')
    expect(formatSignedINR(-1152)).toBe('−₹1,152')
    expect(formatCompactINR(657302)).toBe('₹6.57 L')
    expect(formatCompactINR(12_000_000)).toBe('₹1.20 Cr')
    expect(formatCompactINR(48200)).toBe('₹48,200')
  })
})

describe('IST', () => {
  it('converts UTC instants to IST regardless of the machine timezone', () => {
    expect(istParts('2026-09-19T18:30:00Z')).toMatchObject({ year: 2026, month: 9, day: 20, hour: 0, minute: 0 })
    expect(formatDateTimeIST('2026-10-02T04:30:00Z')).toBe('2 Oct, 10:00 IST')
  })
  it('formats the data window with an exclusive end', () => {
    expect(formatWindow('2026-09-20T00:00:00+05:30', '2026-10-20T00:00:00+05:30')).toBe('20 Sep – 19 Oct 2026')
  })
  it('formats percentages and missing values', () => {
    expect(formatPct(92.456)).toBe('92.5%')
    expect(formatPct(null)).toBe('—')
  })
})
