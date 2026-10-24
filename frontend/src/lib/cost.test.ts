import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { RecEnvelope, Recommendation } from '../types/contract'
import { appliedKey, optionKey, potential, reconcile, totals, type Decisions } from './cost'

const load = (preset: string) =>
  JSON.parse(readFileSync(resolve(__dirname, `../../fallback/api/recommendations/${preset}.json`), 'utf8')) as RecEnvelope
const env = load('default')
const items = env.items
const byName = (n: string) => items.find((i) => i.resource.name === n)!
const accept = (r: Recommendation, key = r.default_option): Decisions => ({
  [r.resource.resource_id]: { resourceId: r.resource.resource_id, status: 'accepted', optionKey: key, targetPlan: r.target?.plan ?? null },
})

describe('optionKey', () => {
  it('orders actions by apply order, not click order', () => {
    expect(optionKey(['schedule', 'resize'])).toBe('resize+schedule')
    expect(optionKey(['delete', 'snapshot'])).toBe('snapshot+delete')
    expect(optionKey(['stop', 'snapshot'])).toBe('snapshot+stop')
    expect(optionKey([])).toBe('none')
  })
  it('matches every option key the data uses', () => {
    for (const r of items) for (const k of Object.keys(r.options)) expect(optionKey(k === 'none' ? [] : (k.split('+') as never))).toBe(k)
  })
})

describe('totals', () => {
  it('with nothing accepted, after equals before and equals the run-rate', () => {
    const t = totals(items, {})
    expect(t.after).toBe(t.before)
    expect(t.saving).toBe(0)
  })

  it('accepting dev-web-03 moves the total by exactly its combined option (F1)', () => {
    const r = byName('dev-web-03')
    const t = totals(items, accept(r))
    expect(r.default_option).toBe('resize+schedule')
    expect(t.before - t.after).toBe(r.options['resize+schedule'].saving_inr)
    expect(r.options['resize+schedule'].saving_inr).toBeLessThan(r.options.resize.saving_inr + r.options.schedule.saving_inr)
  })

  it('accepting a single option of a multi-action card uses that option only (F2)', () => {
    const r = byName('dev-web-03')
    for (const k of ['resize', 'schedule', 'resize+schedule']) {
      const t = totals(items, accept(r, k))
      expect(t.before - t.after).toBe(r.options[k].saving_inr)
    }
  })

  it('total after accepting everything equals the sum of the cards to the rupee (F5)', () => {
    const all: Decisions = {}
    for (const r of items) if (r.verdict === 'recommend' || r.verdict === 'upsize') Object.assign(all, accept(r))
    const t = totals(items, all)
    const cardSum = items.reduce((s, r) => s + r.options[appliedKey(r, all[r.resource.resource_id])].monthly_inr_after, 0)
    expect(t.after).toBe(cardSum)
    expect(t.before - t.saving + t.riskFixes).toBe(t.after)
  })

  it('counts a resource once even if it appears twice in the input', () => {
    const r = byName('dev-web-03')
    const t1 = totals(items, accept(r))
    const t2 = totals([...items, r], accept(r))
    expect(t2).toEqual(t1)
  })

  it('upsize cost goes on its own line, not into savings (F4)', () => {
    const r = byName('prod-search-02')
    const t = totals(items, accept(r))
    expect(r.verdict).toBe('upsize')
    expect(t.saving).toBe(0)
    expect(t.riskFixes).toBe(-r.options.upsize.saving_inr)
    expect(t.after - t.before).toBe(t.riskFixes)
  })

  it('a rejected or unknown option falls back to no change', () => {
    const r = byName('dev-web-03')
    const id = r.resource.resource_id
    expect(appliedKey(r, { resourceId: id, status: 'rejected', optionKey: 'resize', targetPlan: 'B2' })).toBe('none')
    expect(appliedKey(r, { resourceId: id, status: 'accepted', optionKey: 'bogus', targetPlan: 'B2' })).toBe('none')
  })

  it('splits before/after by env, untagged kept separate', () => {
    const t = totals(items, accept(byName('dev-web-03')))
    expect(Object.keys(t.byEnv).sort()).toEqual(['dev', 'prod', 'staging', 'untagged'])
    const sum = Object.values(t.byEnv).reduce((s, e) => s + e.after, 0)
    expect(sum).toBe(t.after)
  })
})

describe('potential', () => {
  it('default preset headline sits in the plausible 15–35% band (F9)', () => {
    const p = potential(items)
    expect(p.pct).toBeGreaterThanOrEqual(15)
    expect(p.pct).toBeLessThanOrEqual(35)
  })
})

describe('reconcile (F8 preset change)', () => {
  it('keeps decisions whose option and target survive, resets the rest with a reason', () => {
    const r = byName('dev-web-03')
    const id = r.resource.resource_id
    const kept = reconcile(accept(r), items)
    expect(kept.reset).toEqual([])
    expect(kept.decisions[id]).toBeDefined()

    const stale: Decisions = { [id]: { resourceId: id, status: 'accepted', optionKey: 'resize+schedule', targetPlan: 'B3' } }
    const out = reconcile(stale, items)
    expect(out.decisions[id]).toBeUndefined()
    expect(out.reset[0]).toMatchObject({ name: 'dev-web-03', why: 'target changed B3 → B2' })
  })

  it('drops an accepted decision when the resource is no longer actionable', () => {
    const r = byName('prod-batch-07')
    const id = r.resource.resource_id
    const out = reconcile({ [id]: { resourceId: id, status: 'accepted', optionKey: 'resize', targetPlan: 'B1' } }, items)
    expect(out.reset[0].why).toBe('now reject')
  })

  it('keeps explicit rejections across presets', () => {
    const r = byName('dev-web-03')
    const id = r.resource.resource_id
    const out = reconcile({ [id]: { resourceId: id, status: 'rejected', optionKey: 'none', targetPlan: null } }, load('max_performance').items)
    expect(out.decisions[id].status).toBe('rejected')
  })
})
