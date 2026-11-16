import { useState } from "react"
import { ApiError, type SearchClient } from "../api/client.ts"
import { EMPTY_FILTERS, planRequest, type FilterDraft } from "../api/requests.ts"
import type { CatalogPayload, CompareBody, ComparePayload } from "../api/types.ts"
import { ComparePanel } from "../components/ComparePanel.tsx"
import { SearchBar } from "../components/SearchBar.tsx"
import { SearchFilters } from "../components/SearchFilters.tsx"
import { presentError } from "../lib/messages.ts"

export function ComparePage({ client, catalog }: { client: SearchClient; catalog: CatalogPayload | null }) {
  const [query, setQuery] = useState("ผลผลิตมันสำปะหลังภาคเหนือปี 2566")
  const [topK, setTopK] = useState(5)
  const [filters, setFilters] = useState<FilterDraft>(EMPTY_FILTERS)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [payload, setPayload] = useState<ComparePayload | null>(null)

  async function submit() {
    const planned = planRequest("compare", query, topK, filters, { enabled: false, metric: "production", operator: "gt", threshold: "", unit: "t" })
    setLoading(true)
    setError(null)
    try {
      setPayload(await client.compare(planned.body as CompareBody))
    } catch (caught) {
      setPayload(null)
      if (caught instanceof ApiError) setError(presentError(caught.status, caught.message))
      else setError(caught instanceof Error ? caught.message : "ไม่สามารถเปรียบเทียบได้")
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="page">
      <h2>เปรียบเทียบ Dictionary และ Semantic</h2>
      <p className="note">ลำดับของแต่ละฝั่งคงตามที่แบ็กเอนด์ส่งกลับ และไม่มีการรวมคะแนน</p>
      <SearchBar query={query} topK={topK} loading={loading} onQueryChange={setQuery} onTopKChange={setTopK} onSubmit={() => void submit()} onExample={setQuery} />
      <SearchFilters
        mode="compare"
        catalog={catalog}
        filters={filters}
        numeric={{ enabled: false, metric: "production", operator: "gt", threshold: "", unit: "t" }}
        onFilters={setFilters}
        onNumeric={() => undefined}
      />
      {loading ? <p className="loading" role="status">กำลังค้นหา</p> : null}
      {error ? <p className="warning" role="alert">{error}</p> : null}
      {payload ? <ComparePanel payload={payload} sources={catalog?.sources ?? []} /> : null}
    </section>
  )
}
