import { useRef, useState } from "react"
import { ApiError, type SearchClient } from "../api/client.ts"
import { EMPTY_FILTERS, EMPTY_NUMERIC, planRequest, type FilterDraft, type NumericDraft } from "../api/requests.ts"
import type { CatalogPayload, CompareBody, ComparePayload, HybridPayload, SearchMode, SemanticPayload } from "../api/types.ts"
import { AvailabilityNotice } from "../components/AvailabilityNotice.tsx"
import { SearchBar } from "../components/SearchBar.tsx"
import { SearchFilters } from "../components/SearchFilters.tsx"
import { SearchModeSelector } from "../components/SearchModeSelector.tsx"
import { SearchResults } from "../components/SearchResults.tsx"
import { ComparePanel } from "../components/ComparePanel.tsx"
import { filterSummary, semanticAvailability, splitRows } from "../lib/results.ts"
import { timingTotal } from "../lib/format.ts"
import { presentError } from "../lib/messages.ts"
import type { SourceMeta } from "../lib/source.ts"

interface SearchPageProps {
  client: SearchClient
  catalog: CatalogPayload | null
  dictionaryOnly?: boolean
}

type View =
  | { kind: "semantic"; payload: SemanticPayload }
  | { kind: "hybrid"; payload: HybridPayload }
  | { kind: "dictionary"; payload: ComparePayload }
  | { kind: "compare"; payload: ComparePayload }

export function SearchPage({ client, catalog, dictionaryOnly = false }: SearchPageProps) {
  const [query, setQuery] = useState("")
  const [topK, setTopK] = useState(5)
  const [mode, setMode] = useState<SearchMode>(dictionaryOnly ? "dictionary" : "hybrid")
  const [filters, setFilters] = useState<FilterDraft>(EMPTY_FILTERS)
  const [numeric, setNumeric] = useState<NumericDraft>(EMPTY_NUMERIC)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const requestId = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  function changeMode(next: SearchMode) {
    if (next === mode) return
    abortRef.current?.abort()
    abortRef.current = null
    requestId.current += 1
    setMode(next)
    setView(null)
    setError(null)
    setLoading(false)
  }

  async function submit() {
    const planned = planRequest(mode, query, topK, filters, numeric)
    if (!planned.body.query) return
    const id = requestId.current + 1
    requestId.current = id
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      let next: View
      if (planned.mode === "semantic") next = { kind: "semantic", payload: await client.search(planned.body, controller.signal) }
      else if (planned.mode === "hybrid") next = { kind: "hybrid", payload: await client.hybrid(planned.body, controller.signal) }
      else next = { kind: planned.mode, payload: await client.compare(planned.body as CompareBody, controller.signal) }
      if (requestId.current !== id) return
      setView(next)
      setHistory((current) => [planned.body.query, ...current.filter((item) => item !== planned.body.query)].slice(0, 8))
    } catch (caught) {
      if (requestId.current !== id) return
      if (caught instanceof ApiError && caught.code === "aborted") return
      setView(null)
      setError(messageFor(caught))
    } finally {
      if (requestId.current === id) setLoading(false)
    }
  }

  return (
    <section className="page">
      {dictionaryOnly
        ? <p className="note">ระบุพืช ภาค และปีในคำค้น เช่น ข้าวนาปีภาคใต้ปี 2566</p>
        : <SearchModeSelector mode={mode} onChange={changeMode} />}
      <SearchBar
        query={query}
        topK={topK}
        loading={loading}
        onQueryChange={setQuery}
        onTopKChange={setTopK}
        onSubmit={() => void submit()}
        onExample={(value) => setQuery(value)}
      />
      {history.length ? (
        <div className="history" aria-label="ประวัติการค้นหาในเซสชันนี้">
          {history.map((item) => (
            <button key={item} type="button" className="chip" onClick={() => setQuery(item)}>
              {item}
            </button>
          ))}
        </div>
      ) : null}
      {!dictionaryOnly && <SearchFilters mode={mode} catalog={catalog} filters={filters} numeric={numeric} onFilters={setFilters} onNumeric={setNumeric} />}
      {loading ? <p className="loading" role="status">กำลังค้นหา</p> : null}
      {error ? <p className="warning" role="alert">{error}</p> : null}
      {view ? <ViewBody view={view} sources={catalog?.sources ?? []} /> : null}
    </section>
  )
}

function ViewBody({ view, sources }: { view: View; sources: SourceMeta[] }) {
  if (view.kind === "compare") return <ComparePanel payload={view.payload} sources={sources} />
  if (view.kind === "dictionary") {
    const section = view.payload.dictionary
    const groups = splitRows(section?.results, section?.context_results, section?.availability_status ?? "supported")
    return (
      <>
        <AvailabilityNotice status={section?.availability_status} />
        <SearchResults
          answers={groups.answers}
          context={groups.context}
          countLabel={`${groups.answers.length} แถวคำตอบ`}
          timingMs={section?.timing_ms ?? null}
          activeFilters={["dictionary parser only"]}
          warnings={section?.warnings ?? []}
          unapplied={[]}
          details={[{ label: "โหมด", value: "dictionary" }]}
          emptyKind={emptyKind(section?.availability_status, groups.answers.length, groups.context.length)}
          sources={sources}
        />
      </>
    )
  }
  if (view.kind === "semantic") {
    const availability = semanticAvailability(view.payload)
    const rows = view.payload.results.map((row) => ({
      ...row,
      answers_requested_measure: row.answers_requested_measure ?? availability === "supported",
    }))
    const groups = splitRows(rows, [], availability)
    return (
      <>
        <AvailabilityNotice status={availability} />
        <SearchResults
          answers={groups.answers}
          context={groups.context}
          countLabel={`${groups.answers.length} แถวคำตอบ จาก ${view.payload.count} แถวที่ส่งกลับ`}
          timingMs={timingTotal(view.payload.timing_ms)}
          activeFilters={filterSummary(view.payload.parsed_filters)}
          warnings={view.payload.warnings ?? []}
          unapplied={[]}
          details={[
            { label: "parsed_filters", value: JSON.stringify(view.payload.parsed_filters ?? {}) },
            { label: "search_engine", value: view.payload.search_engine ?? "local-bge-m3" },
          ]}
          emptyKind={emptyKind(availability, groups.answers.length, groups.context.length)}
          sources={sources}
        />
      </>
    )
  }
  const groups = splitRows(view.payload.results, view.payload.context_results, view.payload.availability_status ?? "supported")
  const applied = view.payload.applied_filters ?? {}
  return (
    <>
      <AvailabilityNotice status={view.payload.availability_status} />
      <SearchResults
        answers={groups.answers}
        context={groups.context}
        countLabel={`${groups.answers.length} แถวคำตอบ · เข้าเกณฑ์ ${view.payload.eligible_count ?? 0} ระเบียน`}
        timingMs={timingTotal(view.payload.timing_ms)}
        activeFilters={Object.entries(applied)
          .filter(([, value]) => value !== null && value !== undefined && !(Array.isArray(value) && value.length === 0))
          .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : String(value)}`)}
        warnings={[...(view.payload.warnings ?? []), ...(view.payload.missing_groups ?? []).map((crop) => `ไม่มีข้อมูลพืช ${crop}`)]}
        unapplied={view.payload.unapplied_conditions ?? []}
        details={[
          { label: "parsed_intent", value: JSON.stringify(view.payload.parsed_intent ?? {}) },
          { label: "ranking_method", value: view.payload.ranking_method ?? "eligibility-first-bge-m3" },
          { label: "embedding_model", value: view.payload.embedding_model ?? "" },
          { label: "applied_numeric", value: JSON.stringify(view.payload.applied_numeric ?? []) },
        ]}
        emptyKind={emptyKind(view.payload.availability_status, groups.answers.length, groups.context.length)}
        sources={sources}
      />
    </>
  )
}

function emptyKind(status: string | null | undefined, answers: number, context: number): "none" | "no-match" | "unsupported" {
  if (answers > 0 || context > 0) return "none"
  if (status === "unsupported") return "unsupported"
  return "no-match"
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return presentError(error.status, error.message)
  return "ไม่สามารถค้นหาได้"
}
