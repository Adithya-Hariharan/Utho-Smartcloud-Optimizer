// One hook per backend endpoint (PLAN §10, API_CONTRACT.md).
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { MetricName, MetricSeries, PresetId, RecEnvelope, ResourceDetail, ResourceFilters, ResourceRow, Step } from '../types/contract'
import type { AlertsResponse, Assumptions, DataQuality, Forecast, ReplaySeries, Scorecard, Summary, WhatIfRequest, WhatIfResponse } from '../types/api'
import { getJson, postJson } from './client'

// Engine output is fixed for a given dataset + config, so it is fetched once per session.
const stable = { staleTime: Infinity, gcTime: Infinity } as const

const qs = (params: Record<string, string | undefined>) => {
  const p = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString()
  return p ? `?${p}` : ''
}

export const useAssumptions = () => useQuery({ queryKey: ['assumptions'], queryFn: () => getJson<Assumptions>('/assumptions'), ...stable })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: () => getJson<Summary>('/summary'), ...stable })
export const useAlerts = () => useQuery({ queryKey: ['alerts'], queryFn: () => getJson<AlertsResponse>('/alerts'), ...stable })
export const useDataQuality = () => useQuery({ queryKey: ['data-quality'], queryFn: () => getJson<DataQuality>('/data-quality'), ...stable })
export const useScorecard = () => useQuery({ queryKey: ['scorecard'], queryFn: () => getJson<Scorecard>('/scorecard'), ...stable })
export const useForecast = (days = 90) => useQuery({ queryKey: ['forecast', days], queryFn: () => getJson<Forecast>(`/forecast?days=${days}`), ...stable })

/** Fleet list; region / env / team / type are filtered by the server. */
export const useResources = (filters: ResourceFilters = {}) =>
  useQuery({
    queryKey: ['resources', filters.region ?? '', filters.env ?? '', filters.team ?? '', filters.type ?? ''],
    queryFn: () => getJson<ResourceRow[]>(`/resources${qs({ ...filters })}`),
    placeholderData: keepPreviousData,
    ...stable,
  })

/** Inventory + features + trace + data-quality report for one resource. */
export const useResourceDetail = (resourceId: string | null) =>
  useQuery({ queryKey: ['resource', resourceId], queryFn: () => getJson<ResourceDetail>(`/resources/${resourceId}`), enabled: !!resourceId, ...stable })

export const useRecommendations = (preset: PresetId) =>
  useQuery({ queryKey: ['recommendations', preset], queryFn: () => getJson<RecEnvelope>(`/recommendations?preset=${preset}`), ...stable })

/** One metric: hourly mean + max by default (keeps peaks), 5-minute on request. Only call when has_metrics. */
export const useMetric = (resourceId: string | null, metric: MetricName, step: Step = '1h') =>
  useQuery({
    queryKey: ['metric', resourceId, metric, step],
    queryFn: () => getJson<MetricSeries>(`/resources/${resourceId}/metrics?metric=${metric}&step=${step}`),
    enabled: !!resourceId,
    placeholderData: keepPreviousData,
    ...stable,
  })

/** Peak Replay series computed by the engine. `preset` picks the target plan (not in PLAN §10; see API_CONTRACT.md). */
export const useReplay = (resourceId: string | null, preset: PresetId) =>
  useQuery({
    queryKey: ['replay', resourceId, preset],
    queryFn: () => getJson<ReplaySeries>(`/resources/${resourceId}/replay?preset=${preset}`),
    enabled: !!resourceId,
    ...stable,
  })

export const useWhatIf = (input: WhatIfRequest) =>
  useQuery({
    queryKey: ['whatif', input.env, input.off, input.weekends],
    queryFn: () => postJson<WhatIfResponse>('/whatif', input),
    placeholderData: keepPreviousData,
    ...stable,
  })
