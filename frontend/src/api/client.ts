// The only way the app gets data: HTTP calls to /api (PLAN §10). In dev, Vite proxies /api to the
// FastAPI server (VITE_API_URL, default http://localhost:8000). While that server is not running, the
// dev server answers from fallback data and marks it with X-Data-Source: fallback (TEMPORARY).
import { useSource } from '../store/source'

export class ApiError extends Error {
  constructor(
    readonly method: string,
    readonly path: string,
    readonly status: number | null,
    detail: string,
  ) {
    super(status === null ? `Backend not reachable (${method} ${path}): ${detail}` : `${method} ${path} → ${status}${detail ? `: ${detail}` : ''}`)
  }
}

async function request(method: 'GET' | 'POST', path: string, body?: unknown): Promise<Response> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (e) {
    throw new ApiError(method, `/api${path}`, null, (e as Error).message)
  }
  useSource.getState().setFallback(res.headers.get('X-Data-Source') === 'fallback')
  if (!res.ok) {
    // the Vite proxy answers 502/504 when nothing is listening on the backend port
    if (res.status === 502 || res.status === 504) throw new ApiError(method, `/api${path}`, null, `proxy got ${res.status}`)
    const text = await res.text().catch(() => '')
    throw new ApiError(method, `/api${path}`, res.status, text.slice(0, 200))
  }
  return res
}

export async function getJson<T>(path: string): Promise<T> {
  return (await (await request('GET', path)).json()) as T
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return (await (await request('POST', path, body)).json()) as T
}

/** POST that returns a file (Content-Disposition: attachment; filename=...). */
export async function postFile(path: string, body: unknown): Promise<{ blob: Blob; filename: string }> {
  const res = await request('POST', path, body)
  const cd = res.headers.get('Content-Disposition') ?? ''
  const filename = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? 'export'
  return { blob: await res.blob(), filename }
}
