import { lazy, Suspense, useEffect, useMemo, useState } from "react"
import { Leaf } from "lucide-react"
import { createApiClient, type SearchClient } from "./api/client.ts"
import type { CatalogPayload } from "./api/types.ts"
import { StatusIndicator } from "./components/StatusIndicator.tsx"
import { ComparePage } from "./pages/ComparePage.tsx"
import { SearchPage } from "./pages/SearchPage.tsx"

const EvaluationPage = lazy(() =>
  import("./pages/EvaluationPage.tsx").then((module) => ({ default: module.EvaluationPage })),
)

type PageId = "search" | "compare" | "evaluation"
const dictionaryOnly = import.meta.env.VITE_DICTIONARY_DEMO === "1"

export default function App({ client }: { client?: SearchClient }) {
  const api = useMemo(() => client ?? createApiClient(), [client])
  const [page, setPage] = useState<PageId>("search")
  const [health, setHealth] = useState("กำลังตรวจ")
  const [ready, setReady] = useState("กำลังตรวจ")
  const [catalog, setCatalog] = useState<CatalogPayload | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.health().then((payload) => active && setHealth(payload.status)).catch(() => active && setHealth("ไม่พร้อม"))
    api.ready().then((payload) => active && setReady(payload.status)).catch(() => active && setReady("ไม่พร้อม"))
    api.catalog().then((payload) => active && setCatalog(payload)).catch(() => active && setCatalogError("โหลดรายการตัวกรองไม่สำเร็จ"))
    return () => {
      active = false
    }
  }, [api])

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">S1-G14 · ข้อมูลผลผลิตการเกษตร</p>
          <h1>
            <Leaf size={22} aria-hidden="true" /> {dictionaryOnly ? "ค้นหาผลผลิตการเกษตร" : "ค้นหาเชิงความหมาย"}
          </h1>
        </div>
        <StatusIndicator health={health} ready={ready} readyLabel={dictionaryOnly ? "ฐานข้อมูล" : "โมเดล"} />
      </header>
      <nav className="nav" aria-label="หน้าหลัก">
        <button type="button" className={page === "search" ? "active" : ""} onClick={() => setPage("search")}>
          ค้นหา
        </button>
        {!dictionaryOnly && <button type="button" className={page === "compare" ? "active" : ""} onClick={() => setPage("compare")}>
          เปรียบเทียบ
        </button>}
        <button type="button" className={page === "evaluation" ? "active" : ""} onClick={() => setPage("evaluation")}>
          การประเมิน
        </button>
      </nav>
      <main>
        {catalogError ? <p className="warning" role="alert">{catalogError}</p> : null}
        {page === "search" ? <SearchPage client={api} catalog={catalog} dictionaryOnly={dictionaryOnly} /> : null}
        {page === "compare" ? <ComparePage client={api} catalog={catalog} /> : null}
        {page === "evaluation" ? (
          <Suspense fallback={<p className="loading" role="status">กำลังเปิดแดชบอร์ดการประเมิน</p>}>
            <EvaluationPage client={api} />
          </Suspense>
        ) : null}
      </main>
    </div>
  )
}
