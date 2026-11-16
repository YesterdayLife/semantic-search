import type { BackendSection, ComparePayload, SearchResult } from "../api/types.ts"
import { formatMilliseconds } from "../lib/format.ts"
import { translateMessage } from "../lib/messages.ts"
import type { SourceMeta } from "../lib/source.ts"
import { AvailabilityNotice } from "./AvailabilityNotice.tsx"
import { ResultCard } from "./ResultCard.tsx"

function ids(rows: SearchResult[] | undefined): string[] {
  return (rows ?? []).map((row) => row.process_id).filter((id): id is string => Boolean(id))
}

function Column({ title, section, scoreKind, sources }: { title: string; section: BackendSection | null | undefined; scoreKind: "reason" | "cosine"; sources: SourceMeta[] }) {
  const rows = section?.results ?? []
  const context = section?.context_results ?? []
  return (
    <section className="compare-column">
      <h3>{title}</h3>
      <p>เวลา: {formatMilliseconds(section?.timing_ms)}</p>
      <AvailabilityNotice status={section?.availability_status} />
      {section?.error?.message ? <p className="warning">{translateMessage(section.error.message)}</p> : null}
      {(section?.warnings ?? []).map((warning) => (
        <p key={warning} className="warning">
          {translateMessage(warning)}
        </p>
      ))}
      <p className="score-kind">
        {scoreKind === "reason" ? "คอลัมน์นี้แสดงเหตุผลการจับคู่ ไม่ใช่ cosine" : "คอลัมน์นี้แสดง cosine similarity ไม่ใช่ปริมาณผลผลิต"}
      </p>
      {rows.length ? rows.map((row, index) => <ResultCard key={`${row.process_id}-${index}`} row={row} rank={index + 1} sources={sources} />) : <p className="empty">ไม่มีแถวคำตอบ</p>}
      {context.length ? (
        <div className="context">
          <h4>ระเบียนบริบท</h4>
          {context.map((row, index) => (
            <ResultCard key={`ctx-${row.process_id}-${index}`} row={{ ...row, answers_requested_measure: false }} rank={index + 1} sources={sources} />
          ))}
        </div>
      ) : null}
    </section>
  )
}

export function ComparePanel({ payload, sources = [] }: { payload: ComparePayload; sources?: SourceMeta[] }) {
  const left = new Set(ids(payload.dictionary?.results))
  const right = new Set(ids(payload.semantic?.results))
  const shared = [...left].filter((id) => right.has(id))
  const onlyDictionary = [...left].filter((id) => !right.has(id))
  const onlySemantic = [...right].filter((id) => !left.has(id))
  const comparable = payload.filter_comparability?.directly_comparable !== false
  return (
    <div className="compare-panel">
      <p className="note">{translateMessage(payload.note || "เหตุผลของพจนานุกรมและ cosine ไม่ได้อยู่ในสเกลเดียวกัน")}</p>
      {payload.score_comparison === null ? <p className="note">score_comparison เป็น null ไม่มีการหลอมคะแนน</p> : null}
      {!comparable ? (
        <div className="warning">
          <p>สองชุดผลลัพธ์เปรียบเทียบกันตรง ๆ ไม่ได้ เพราะตัวกรองหรือเงื่อนไขต่างกัน</p>
          <ul>
            {(payload.filter_comparability?.reasons ?? []).map((reason) => (
              <li key={reason}>{translateMessage(reason)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="compare-grid">
        <Column title="Dictionary Search" section={payload.dictionary} scoreKind="reason" sources={sources} />
        <Column title="BGE-M3 Semantic Search" section={payload.semantic} scoreKind="cosine" sources={sources} />
      </div>
      <section className="overlap">
        <h3>process_id ที่ซ้อนทับกัน</h3>
        <p>ร่วมกัน: {shared.length ? shared.join(", ") : "ไม่มี"}</p>
        <p>เฉพาะ Dictionary: {onlyDictionary.length ? onlyDictionary.join(", ") : "ไม่มี"}</p>
        <p>เฉพาะ Semantic: {onlySemantic.length ? onlySemantic.join(", ") : "ไม่มี"}</p>
      </section>
    </div>
  )
}
