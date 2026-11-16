export type SearchMode = "dictionary" | "semantic" | "hybrid" | "compare"
export type Availability = "supported" | "partially_supported" | "unsupported" | string

export interface FilterSet {
  crop_id?: string
  year_ce?: number
  region_code?: string
  season?: string
  spatial_level?: string
  source_id?: string
}

export interface NumericConstraint {
  metric: "production" | "yield_harvested" | "yield_planted" | "area_harvested" | "area_planted"
  operator: "gt" | "gte" | "lt" | "lte"
  threshold: number
  unit: "t" | "kg/rai" | "rai"
}

export interface SearchBody {
  query: string
  top_k: number
  filters?: FilterSet
}

export interface CompareBody extends SearchBody {
  mode: "dictionary" | "semantic" | "compare" | "semantic-fallback"
}

export interface HybridBody extends SearchBody {
  numeric?: NumericConstraint
}

export interface Indicator {
  metric_code: string
  value: number | null
  unit: string | null
}

export interface SearchResult {
  process_id: string | null
  crop?: { crop_id: string | null; crop_name: string | null } | null
  year?: { year_ce: number | null; year_original?: string | null; calendar?: string | null } | null
  region?: { region_code: string | null; region_name: string | null; area?: string | null } | null
  season?: string | null
  spatial_level?: string | null
  production_quantity?: number | null
  production_unit?: string | null
  source?: { source_id: string | null; agency: string | null; title: string | null } | null
  similarity_score?: number | null
  match_reason?: string | null
  eligibility_reason?: string | null
  answers_requested_measure?: boolean
  indicators?: Indicator[]
  availability_status?: string | null
}

export interface SemanticPayload {
  query: string
  parsed_filters?: FilterSet
  count: number
  results: SearchResult[]
  warnings?: string[]
  unavailable_measures?: string[]
  search_engine?: string
  embedding_model?: string
  model_revision?: string
  timing_ms?: { embed?: number; qdrant?: number; sqlite?: number; total?: number }
}

export interface BackendSection {
  ok?: boolean
  backend?: string
  search_mode?: string
  availability_status?: string | null
  count?: number
  results?: SearchResult[]
  context_results?: SearchResult[]
  warnings?: string[]
  timing_ms?: number | null
  error?: { code?: string; message?: string } | null
  original?: Record<string, unknown> | null
}

export interface ComparePayload {
  query: string
  mode?: string
  ok?: boolean
  availability_status?: { dictionary?: string | null; semantic?: string | null }
  dictionary?: BackendSection | null
  semantic?: BackendSection | null
  warnings?: string[]
  errors?: Record<string, { code?: string; message?: string }>
  score_comparison?: null
  note?: string
  filter_comparability?: { directly_comparable?: boolean; reasons?: string[] }
  timing_ms?: { dictionary?: number | null; semantic?: number | null; total?: number }
}

export interface HybridPayload {
  ok?: boolean
  query: string
  search_mode?: string
  availability_status?: string
  parsed_intent?: Record<string, unknown>
  requested_measure?: string[]
  applied_filters?: Record<string, unknown>
  applied_numeric?: NumericConstraint[]
  unapplied_conditions?: string[]
  eligible_count?: number
  count: number
  results: SearchResult[]
  context_results?: SearchResult[]
  missing_groups?: string[]
  omitted_groups?: string[]
  warnings?: string[]
  ranking_method?: string
  embedding_model?: string
  model_revision?: string
  embedding_skipped?: boolean
  score_comparison?: null
  timing_ms?: Record<string, number | null>
}

export interface CatalogOption {
  crop_id?: string
  crop_name?: string
  region_code?: string
  region_name?: string
  source_id?: string
  agency?: string
  title?: string
}

export interface CatalogPayload {
  crops: CatalogOption[]
  regions: CatalogOption[]
  seasons: string[]
  spatial_levels: string[]
  sources: CatalogOption[]
  years: number[]
  process_count: number
  numeric_metrics: { metric: NumericConstraint["metric"]; unit: NumericConstraint["unit"] }[]
  numeric_operators: NumericConstraint["operator"][]
}

export interface LatencyStats {
  count?: number
  mean_ms?: number
  median_ms?: number
  p95_ms?: number
}

export interface MetricBlock {
  ranked_queries?: number
  precision_at_k?: number | null
  recall_at_k?: number | null
  hit_at_k?: number | null
  mrr?: number | null
  ndcg_at_k?: number | null
  crop_coverage?: number | null
  numeric_condition_correctness?: number | null
  empty_result_correctness?: number | null
  availability_accuracy?: number | null
}

export interface EvaluationReport {
  top_k?: number
  query_count?: number
  policy?: { precision_denominator?: string }
  backends?: Record<string, { aggregate?: MetricBlock; phase6_subset?: MetricBlock }>
  comparison?: { mean_retrieved_jaccard?: number; different_top_sets?: number; ranked_queries?: number }
  benchmark?: {
    repetitions?: number
    warmup?: number
    model_initialization_ms?: number
    dictionary_warm?: LatencyStats
    semantic_warm?: LatencyStats
    hybrid_warm?: LatencyStats
    compare_warm?: LatencyStats
  }
  report_note?: string
}

export interface HealthPayload {
  status: string
}

export interface ReadyPayload {
  status: string
  collection?: string
  points?: number
  process_count?: number
  embedding_model?: string
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string; details?: { field?: string; message?: string }[] }
}
