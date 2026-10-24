#!/usr/bin/env node
// Checkpoint gate for the frontend.
//
//   npm run verify                 walk checkpoints in order, stop at the first failure
//   npm run verify -- --upto CP05  only go as far as CP05
//   npm run verify -- --force      ignore cached passes and re-run everything
//   npm run verify:watch           re-run automatically whenever code changes
//   npm run verify -- --live       browser tests against the real backend on :8000
//
// A checkpoint that passed is skipped only while the code is byte-identical to when it
// passed. Touch any source, test, script or config file and every checkpoint is
// re-checked on the next run, so a regression in an earlier feature blocks the later ones.
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, watch, writeFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = resolve(fileURLToPath(import.meta.url), '../..')
const REPO = resolve(ROOT, '..')
const STATE_DIR = join(ROOT, '.verify')
const STATE_FILE = join(STATE_DIR, 'state.json')

const WATCH_DIRS = ['src', 'e2e', 'scripts', 'public', 'fallback']
const WATCH_FILES = [
  'package.json', 'index.html', 'vite.config.ts', 'tailwind.config.js', 'postcss.config.js',
  'tsconfig.json', 'tsconfig.app.json', 'tsconfig.node.json', 'playwright.config.ts', 'checkpoints.config.mjs',
]
const IGNORE = new Set(['node_modules', 'dist', '.verify', 'test-results', 'playwright-report', 'data'])

const args = process.argv.slice(2)
const FORCE = args.includes('--force')
const WATCH = args.includes('--watch')
const UPTO = args.includes('--upto') ? args[args.indexOf('--upto') + 1] : null
// --live: browser tests hit the real backend through the Vite proxy instead of the in-test stub
const LIVE = args.includes('--live')

const c = (code) => (s) => (process.stdout.isTTY ? `\x1b[${code}m${s}\x1b[0m` : s)
const green = c(32), red = c(31), yellow = c(33), dim = c(2), bold = c(1)

function walk(dir, out) {
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    if (IGNORE.has(name)) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

// Per-file hashes of everything that can change behaviour, plus the source dataset.
function snapshot() {
  const files = WATCH_DIRS.flatMap((d) => walk(join(ROOT, d), []))
  for (const f of WATCH_FILES) if (existsSync(join(ROOT, f))) files.push(join(ROOT, f))
  for (const f of walk(join(REPO, 'data'), [])) files.push(f)
  const hashes = {}
  for (const f of files.sort()) {
    hashes[relative(REPO, f).replaceAll('\\', '/')] = createHash('sha256').update(readFileSync(f)).digest('hex').slice(0, 16)
  }
  const fingerprint = createHash('sha256').update(JSON.stringify(hashes) + (LIVE ? ':live' : '')).digest('hex').slice(0, 16)
  return { fingerprint, hashes }
}

function changedFiles(before = {}, after) {
  const all = new Set([...Object.keys(before), ...Object.keys(after)])
  return [...all].filter((f) => before[f] !== after[f]).sort()
}

function loadState() {
  try { return JSON.parse(readFileSync(STATE_FILE, 'utf8')) } catch { return { passed: {}, hashes: {} } }
}
function saveState(s) {
  mkdirSync(STATE_DIR, { recursive: true })
  writeFileSync(STATE_FILE, JSON.stringify(s, null, 2))
}

function commandFor([kind, target]) {
  switch (kind) {
    case 'typecheck': return 'npx tsc -b --noEmit'
    case 'data': return 'node scripts/check_fixtures.mjs'
    case 'unit': return `npx vitest run ${target ?? ''} --reporter=dot`
    case 'e2e': return `npx playwright test ${target ?? ''} --reporter=line`
    case 'build': return 'npx vite build --logLevel warn'
    default: throw new Error(`unknown check kind ${kind}`)
  }
}

function run(cmd) {
  return new Promise((done) => {
    const t0 = Date.now()
    const p = spawn(cmd, { cwd: ROOT, shell: true, env: { ...process.env, FORCE_COLOR: '0', CI: '1', ...(LIVE ? { E2E_LIVE: '1' } : {}) } })
    let out = ''
    p.stdout.on('data', (d) => (out += d))
    p.stderr.on('data', (d) => (out += d))
    p.on('close', (code) => done({ ok: code === 0, out, secs: (Date.now() - t0) / 1000 }))
  })
}

async function verifyOnce() {
  const checkpoints = (await import(pathToFileURL(join(ROOT, 'checkpoints.config.mjs')).href + `?t=${Date.now()}`)).default
  const state = loadState()
  const snap = snapshot()
  const changed = changedFiles(state.hashes, snap.hashes)
  const anyPassed = Object.keys(state.passed).length > 0

  console.log(bold(`\n── verify @ ${new Date().toLocaleTimeString()} ── fingerprint ${snap.fingerprint}`))
  if (anyPassed && changed.length && !FORCE) {
    console.log(yellow(`Code changed since the last run → every checkpoint is re-checked. Changed (${changed.length}):`))
    for (const f of changed.slice(0, 15)) console.log(dim(`   ${f}`))
    if (changed.length > 15) console.log(dim(`   … ${changed.length - 15} more`))
  }

  const results = []
  const ran = new Map() // a check shared by several checkpoints runs once per verify
  let blocked = false
  let pastUpto = false
  for (const cp of checkpoints) {
    if (pastUpto) { results.push([cp, 'upto']); continue }
    if (blocked) { results.push([cp, 'skip']); continue }
    if (!FORCE && state.passed[cp.id] === snap.fingerprint) { results.push([cp, 'cached']); continue }

    process.stdout.write(`${cp.id}  ${cp.title} … `)
    let failure = null, secs = 0
    for (const check of cp.checks) {
      const cmd = commandFor(check)
      if (!ran.has(cmd)) ran.set(cmd, await run(cmd))
      const r = ran.get(cmd)
      secs += r.secs
      if (!r.ok) { failure = { cmd, out: r.out }; break }
    }
    if (failure) {
      console.log(red('FAIL'))
      console.log(dim(`   $ ${failure.cmd}`))
      console.log(failure.out.trim().split('\n').slice(-80).map((l) => '   ' + l).join('\n'))
      delete state.passed[cp.id]
      results.push([cp, 'fail'])
      blocked = true
    } else {
      console.log(green(`PASS`) + dim(` ${secs.toFixed(1)}s`))
      state.passed[cp.id] = snap.fingerprint
      results.push([cp, 'pass'])
    }
    if (UPTO && cp.id === UPTO) pastUpto = true
  }

  // Anything after a failure is no longer trusted.
  for (const [cp, status] of results) if (status === 'skip' || status === 'fail') delete state.passed[cp.id]
  state.hashes = snap.hashes
  saveState(state)

  console.log(bold('\nCheckpoint            Status'))
  for (const [cp, status] of results) {
    const label = { pass: green('PASS'), cached: green('PASS') + dim(' (unchanged)'), fail: red('FAIL'), skip: dim('not attempted'), upto: dim('beyond --upto') }[status]
    console.log(`${cp.id}  ${cp.title.padEnd(52).slice(0, 52)} ${label}`)
  }
  const failed = results.find(([, s]) => s === 'fail')
  const done = results.filter(([, s]) => s === 'pass' || s === 'cached').length
  console.log(failed
    ? red(`\nBlocked at ${failed[0].id}. Later checkpoints are not attempted until it passes.`)
    : green(`\n${done}/${checkpoints.length} checkpoints verified.`))
  return !failed
}

if (!WATCH) {
  process.exit((await verifyOnce()) ? 0 : 1)
} else {
  let running = false, again = false, timer = null
  const trigger = () => {
    clearTimeout(timer)
    timer = setTimeout(async () => {
      if (running) { again = true; return }
      running = true
      do { again = false; await verifyOnce() } while (again)
      running = false
      console.log(dim('\nwatching for changes…'))
    }, 1500)
  }
  for (const d of WATCH_DIRS) {
    if (!existsSync(join(ROOT, d))) continue
    watch(join(ROOT, d), { recursive: true }, (_e, f) => { if (f && !f.split(/[\\/]/).some((p) => IGNORE.has(p))) trigger() })
  }
  for (const f of WATCH_FILES) if (existsSync(join(ROOT, f))) watch(join(ROOT, f), trigger)
  trigger()
}
