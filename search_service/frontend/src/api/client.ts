import type {
  CatalogPayload,
  CompareBody,
  ComparePayload,
  EvaluationReport,
  HealthPayload,
  HybridBody,
  HybridPayload,
  ReadyPayload,
  SearchBody,
  SemanticPayload,
} from "./types.ts"

const TIMEOUT_MS = 20000

export class ApiError extends Error {
  status: number
  code: string
  details?: { field?: string; message?: string }[]

  constructor(status: number, code: string, message: string, details?: { field?: string; message?: string }[]) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.details = details
  }
}

export interface SearchClient {
  health: () => Promise<HealthPayload>
  ready: () => Promise<ReadyPayload>
  catalog: () => Promise<CatalogPayload>
  evaluation: () => Promise<EvaluationReport>
  search: (body: SearchBody, signal?: AbortSignal) => Promise<SemanticPayload>
  compare: (body: CompareBody, signal?: AbortSignal) => Promise<ComparePayload>
  hybrid: (body: HybridBody, signal?: AbortSignal) => Promise<HybridPayload>
}

export function createApiClient(base = import.meta.env.VITE_API_BASE ?? "/api"): SearchClient {
  async function send<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
    const parent = init?.signal
    if (parent) {
      if (parent.aborted) controller.abort()
      else parent.addEventListener("abort", () => controller.abort(), { once: true })
    }
    try {
      const response = await fetch(`${base}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
        },
      })
      const text = await response.text()
      const body = text ? (JSON.parse(text) as { error?: { code?: string; message?: string; details?: ApiError["details"] } }) : null
      if (!response.ok) {
        throw new ApiError(
          response.status,
          body?.error?.code ?? "http_error",
          body?.error?.message ?? "The request failed.",
          body?.error?.details,
        )
      }
      return body as T
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiError(0, "aborted", "การค้นหาถูกยกเลิก")
      }
      throw new ApiError(0, "network", "ไม่สามารถเชื่อมต่อบริการค้นหาได้")
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    health: () => send<HealthPayload>("/health"),
    ready: () => send<ReadyPayload>("/ready"),
    catalog: () => send<CatalogPayload>("/catalog"),
    evaluation: () => send<EvaluationReport>("/evaluation-report"),
    search: (body, signal) => send<SemanticPayload>("/search", { method: "POST", body: JSON.stringify(body), signal }),
    compare: (body, signal) => send<ComparePayload>("/compare", { method: "POST", body: JSON.stringify(body), signal }),
    hybrid: (body, signal) => send<HybridPayload>("/hybrid-search", { method: "POST", body: JSON.stringify(body), signal }),
  }
}
