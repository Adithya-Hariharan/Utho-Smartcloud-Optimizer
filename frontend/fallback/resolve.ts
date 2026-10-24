// TEMPORARY fallback for the backend API (PLAN §10). Maps a request to a response built from the
// plan-shaped files in fallback/api/, which docs/reference/mock_engine.py writes from ../data.
//
// Used by:
//  - the dev server (vite.config.ts): only while nothing answers on the backend port.
//  - the browser tests (e2e/fixtures.ts): the in-test API stub.
// The app itself always calls /api/* and does not know this exists. Delete the folder once the
// backend serves everything.
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

export const FALLBACK_DIR = fileURLToPath(new URL('./api/', import.meta.url))

export interface FallbackResponse {
  status: number
  contentType: string
  body: string | Buffer
  headers?: Record<string, string>
}

/** POST /api/whatif body {"env","off":"HH:MM-HH:MM","weekends"} → file key (see whatif_key in mock_engine.py) */
const whatifKey = (b: Record<string, unknown>) => `${b.env}_${String(b.off).replace(/:/g, '').replace('-', '_')}_${b.weekends ? 1 : 0}`

/** request → data file (null = this call has no file) */
export function fileFor(method: string, url: URL, body: Record<string, unknown> | null): string | null {
  const p = url.pathname.replace(/^\/api/, '')
  const q = url.searchParams
  let m
  if (method === 'GET') {
    if (['/assumptions', '/resources', '/summary', '/alerts', '/data-quality', '/scorecard'].includes(p)) return `${p.slice(1)}.json`
    if (p === '/recommendations') return `recommendations/${q.get('preset') ?? 'default'}.json`
    if (p === '/forecast') return `forecast_${q.get('days') ?? '90'}.json`
    if ((m = /^\/resources\/([^/]+)\/metrics$/.exec(p))) return `metrics/${m[1]}/${q.get('metric')}_${q.get('step') ?? '1h'}.json`
    if ((m = /^\/resources\/([^/]+)\/replay$/.exec(p))) return `replay/${q.get('preset') ?? 'default'}/${m[1]}.json`
    if ((m = /^\/resources\/([^/]+)$/.exec(p))) return `resources/${m[1]}.json`
  }
  if (method === 'POST' && p === '/whatif' && body) return `whatif/${whatifKey(body)}.json`
  return null
}

/** data file → the GET endpoint it stands in for (used to read the same data from a live backend) */
export function endpointFor(file: string): string {
  const f = file.replace(/\.json$/, '')
  let m
  if ((m = /^recommendations\/(.+)$/.exec(f))) return `/api/recommendations?preset=${m[1]}`
  if ((m = /^metrics\/([^/]+)\/(.+)_(1h|5m)$/.exec(f))) return `/api/resources/${m[1]}/metrics?metric=${m[2]}&step=${m[3]}`
  if ((m = /^replay\/([^/]+)\/(.+)$/.exec(f))) return `/api/resources/${m[2]}/replay?preset=${m[1]}`
  if ((m = /^forecast_(\d+)$/.exec(f))) return `/api/forecast?days=${m[1]}`
  return `/api/${f}`
}

let ids: Set<string> | null = null
const knownIds = () => (ids ??= new Set((JSON.parse(readFileSync(FALLBACK_DIR + 'resources.json', 'utf8')) as { resource_id: string }[]).map((r) => r.resource_id)))

/** What the server does for GET /api/resources?region=&env=&team=&type= (untagged / unowned match missing tags). */
function filterResources(json: Buffer, q: URLSearchParams): string {
  const rows = JSON.parse(json.toString('utf8')) as Record<string, string | null>[]
  const want = (key: string, field: string, none: string) => (r: Record<string, string | null>) => {
    const v = q.get(key)
    return !v || (v === none ? !r[field] : r[field] === v)
  }
  return JSON.stringify(rows.filter((r) => want('env', 'env', 'untagged')(r) && want('team', 'owner_team', 'unowned')(r) && want('region', 'region', '')(r) && want('type', 'type', '')(r)))
}

const EXPORT_NAMES: Record<string, [string, string]> = {
  csv: ['smartcloud-accepted.csv', 'text/csv'],
  md: ['smartcloud-accepted.md', 'text/markdown'],
  sh: ['apply.sh', 'text/x-shellscript'],
  tf: ['smartcloud-plan.tf', 'text/plain'],
}

/**
 * The fallback answer for one /api request, or null when there is no data for it.
 * POST /api/export has no real generator here: it returns a placeholder file listing what was asked for.
 */
export function resolveFallback(method: string, url: URL, body: Record<string, unknown> | null): FallbackResponse | null {
  if (method === 'POST' && url.pathname === '/api/export' && body) {
    const [name, type] = EXPORT_NAMES[String(body.format)] ?? ['export.txt', 'text/plain']
    const lines = ((body.accepted as { rec_id: string; option_key: string }[]) ?? []).map((a) => `# ${a.rec_id} ${a.option_key}`)
    return {
      status: 200,
      contentType: type,
      headers: { 'Content-Disposition': `attachment; filename="${name}"` },
      body: [`# stub export (${body.format}): the backend builds the real file`, ...lines, ''].join('\n'),
    }
  }
  const file = fileFor(method, url, body)
  // an unknown resource id is a legitimate 404 from the server, not missing data
  const id = /^resources\/([^/]+)\.json$/.exec(file ?? '')?.[1]
  if (id && !knownIds().has(id)) return { status: 404, contentType: 'application/json', body: '{"detail":"resource not found"}' }
  if (!file || !existsSync(FALLBACK_DIR + file)) return null
  const raw = readFileSync(FALLBACK_DIR + file)
  return { status: 200, contentType: 'application/json', body: file === 'resources.json' ? filterResources(raw, url.searchParams) : raw }
}
