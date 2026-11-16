import { lazy, Suspense } from "react"
import type { SearchResult } from "../api/types.ts"
import { formatMilliseconds } from "../lib/format.ts"
import { translateMessage } from "../lib/messages.ts"
import { productionSeries } from "../lib/charts.ts"
import type { SourceMeta } from "../lib/source.ts"
import { ResultCard } from "./ResultCard.tsx"

const ProductionChart = lazy(() =>
  import("./ProductionChart.tsx").then((module) => ({ default: module.ProductionChart })),
)

interface SearchResultsProps {
  answers: SearchResult[]
  context: SearchResult[]
  countLabel: string
  timingMs: number | null
  activeFilters: string[]
  warnings: string[]
  unapplied: string[]
  details: { label: string; value: string }[]
  emptyKind: "none" | "no-match" | "unsupported"
  sources?: SourceMeta[]
}

export function SearchResults({
  answers,
  context,
  countLabel,
  timingMs,
  activeFilters,
  warnings,
  unapplied,
  details,
  emptyKind,
  sources = [],
}: SearchResultsProps) {
  const series = productionSeries(answers)
  return (
    <section className="results" aria-live="polite">
      <header className="result-summary">
        <h2>ผลลัพธ์</h2>
        <p>{countLabel}</p>
        <p>เวลาตอบกลับ: {formatMilliseconds(timingMs)}</p>
        <p>ตัวกรองที่ใช้: {activeFilters.length ? activeFilters.join(", ") : "ไม่มีตัวกรองเพิ่ม"}</p>
      </header>
      {warnings.map((warning) => (
        <p key={warning} className="warning">
          {translateMessage(warning)}
        </p>
      ))}
      {unapplied.length ? (
        <div className="unapplied">
          <h3>เงื่อนไขที่ไม่ได้ใช้</h3>
          <ul>
            {unapplied.map((item) => (
              <li key={item}>{translateMessage(item)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {emptyKind === "no-match" ? <p className="empty">ไม่พบระเบียนที่ตรงกับเงื่อนไข</p> : null}
      {emptyKind === "unsupported" ? <p className="empty">ไม่มีแถวคำตอบ เพราะฐานข้อมูลไม่มีตัวชี้วัดที่ขอ</p> : null}
      <div className="card-list">
        {answers.map((row, index) => (
          <ResultCard key={`${row.process_id}-${index}`} row={row} rank={index + 1} sources={sources} />
        ))}
      </div>
      {series ? (
        <Suspense fallback={<p className="loading" role="status">กำลังเปิดกราฟผลผลิต</p>}>
          <ProductionChart series={series} />
        </Suspense>
      ) : answers.length ? <p className="note">ชุดผลลัพธ์นี้ปนหน่วย พืช แหล่งข้อมูล หรือระดับพื้นที่ จึงแสดงเป็นตารางแทนการรวมกราฟ</p> : null}
      {context.length ? (
        <section className="context" aria-label="ระเบียนบริบท">
          <h3>ระเบียนบริบท ไม่ใช่คำตอบของตัวชี้วัดที่ขอ</h3>
          <div className="card-list">
            {context.map((row, index) => (
              <ResultCard key={`context-${row.process_id}-${index}`} row={{ ...row, answers_requested_measure: false }} rank={index + 1} sources={sources} />
            ))}
          </div>
        </section>
      ) : null}
      {details.length ? (
        <details className="interpretation">
          <summary>การตีความคำค้นและวิธีจัดอันดับ</summary>
          <dl>
            {details.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </section>
  )
}
