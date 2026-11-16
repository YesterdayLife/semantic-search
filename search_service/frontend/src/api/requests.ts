import type { CompareBody, FilterSet, HybridBody, NumericConstraint, SearchBody, SearchMode } from "./types.ts"

export interface FilterDraft {
  crop_id: string
  year_ce: string
  region_code: string
  season: string
  spatial_level: string
  source_id: string
}

export interface NumericDraft {
  enabled: boolean
  metric: NumericConstraint["metric"]
  operator: NumericConstraint["operator"]
  threshold: string
  unit: NumericConstraint["unit"]
}

export const EMPTY_FILTERS: FilterDraft = {
  crop_id: "",
  year_ce: "",
  region_code: "",
  season: "",
  spatial_level: "",
  source_id: "",
}

export const EMPTY_NUMERIC: NumericDraft = {
  enabled: false,
  metric: "production",
  operator: "gt",
  threshold: "",
  unit: "t",
}

const UNIT_FOR_METRIC: Record<NumericConstraint["metric"], NumericConstraint["unit"]> = {
  production: "t",
  yield_harvested: "kg/rai",
  yield_planted: "kg/rai",
  area_harvested: "rai",
  area_planted: "rai",
}

export function unitForMetric(metric: NumericConstraint["metric"]): NumericConstraint["unit"] {
  return UNIT_FOR_METRIC[metric]
}

export function presentFilters(draft: FilterDraft): FilterSet | undefined {
  const filters: FilterSet = {}
  if (draft.crop_id) filters.crop_id = draft.crop_id
  if (draft.year_ce) filters.year_ce = Number(draft.year_ce)
  if (draft.region_code) filters.region_code = draft.region_code
  if (draft.season) filters.season = draft.season
  if (draft.spatial_level) filters.spatial_level = draft.spatial_level
  if (draft.source_id) filters.source_id = draft.source_id
  return Object.keys(filters).length ? filters : undefined
}

export function presentNumeric(draft: NumericDraft): NumericConstraint | undefined {
  if (!draft.enabled) return undefined
  const threshold = Number(draft.threshold.replace(/,/g, ""))
  if (!Number.isFinite(threshold) || threshold <= 0) return undefined
  return {
    metric: draft.metric,
    operator: draft.operator,
    threshold,
    unit: unitForMetric(draft.metric),
  }
}

export interface PlannedRequest {
  mode: SearchMode
  path: "/search" | "/compare" | "/hybrid-search"
  body: SearchBody | CompareBody | HybridBody
}

export function planRequest(mode: SearchMode, query: string, topK: number, filters: FilterDraft, numeric: NumericDraft): PlannedRequest {
  const shared: SearchBody = { query: query.trim(), top_k: topK }
  const present = presentFilters(filters)
  if (present) shared.filters = present
  if (mode === "semantic") return { mode, path: "/search", body: shared }
  if (mode === "dictionary") return { mode, path: "/compare", body: { ...shared, mode: "dictionary" } }
  if (mode === "compare") return { mode, path: "/compare", body: { ...shared, mode: "compare" } }
  const hybrid: HybridBody = { ...shared }
  const condition = presentNumeric(numeric)
  if (condition) hybrid.numeric = condition
  return { mode, path: "/hybrid-search", body: hybrid }
}
