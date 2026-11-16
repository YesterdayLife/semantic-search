import type { SearchResult } from "../api/types.ts"
import { formatQuantity, formatScore, presentEligibility } from "../lib/format.ts"
import { sourceCaption, type SourceMeta } from "../lib/source.ts"

const LEVEL: Record<string, string> = { country: "ประเทศ", region: "ภาค" }
const SEASON: Record<string, string> = { all: "ทั้งหมด", dry: "ฤดูแล้ง", wet: "ฤดูฝน" }

export function ResultCard({ row, rank, sources = [] }: { row: SearchResult; rank: number; sources?: SourceMeta[] }) {
  const crop = row.crop?.crop_name || "ไม่มีข้อมูล"
  const region = row.region?.region_name || row.region?.area || "ไม่มีข้อมูล"
  const season = row.season ? (SEASON[row.season] ?? row.season) : "ไม่มีข้อมูล"
  const level = row.spatial_level ? (LEVEL[row.spatial_level] ?? row.spatial_level) : "ไม่มีข้อมูล"
  const answers = row.answers_requested_measure !== false
  const sourceText = sourceCaption(row.source, sources)
  return (
    <article className="result-card">
      <header>
        <p className="rank">อันดับ {rank}</p>
        <h3>{crop}</h3>
        <p>
          {row.year?.year_ce ?? "ไม่มีข้อมูล"} · {region} · {season} · {level}
        </p>
      </header>
      <p className="quantity">
        <span>ปริมาณผลผลิต</span>
        <strong>{formatQuantity(row.production_quantity, row.production_unit)}</strong>
      </p>
      {sourceText ? <p className="meta">แหล่งข้อมูล: {sourceText}</p> : null}
      {row.similarity_score !== null && row.similarity_score !== undefined ? (
        <p className="score">คะแนนความคล้าย cosine: {formatScore(row.similarity_score)}</p>
      ) : null}
      {row.match_reason ? <p className="reason">เหตุผลการจับคู่พจนานุกรม: {row.match_reason}</p> : null}
      {row.eligibility_reason ? <p className="reason">เหตุผลความเข้าเกณฑ์: {presentEligibility(row.eligibility_reason)}</p> : null}
      <p className="measure">{answers ? "ตอบตัวชี้วัดที่ขอ" : "ไม่ใช่คำตอบของตัวชี้วัดที่ขอ"}</p>
      <details>
        <summary>รายละเอียดทางเทคนิค</summary>
        <dl>
          <div>
            <dt>process_id</dt>
            <dd>{row.process_id || "ไม่มีข้อมูล"}</dd>
          </div>
          <div>
            <dt>crop_id</dt>
            <dd>{row.crop?.crop_id || "ไม่มีข้อมูล"}</dd>
          </div>
          {row.source?.source_id ? (
            <div>
              <dt>source_id</dt>
              <dd>{row.source.source_id}</dd>
            </div>
          ) : null}
          <div>
            <dt>หน่วยจาก SQLite</dt>
            <dd>{row.production_unit || "ไม่มีข้อมูล"}</dd>
          </div>
        </dl>
        {row.indicators?.length ? (
          <table>
            <caption>ตัวชี้วัดที่มีในระเบียน</caption>
            <thead>
              <tr>
                <th>รหัส</th>
                <th>ค่า</th>
                <th>หน่วย</th>
              </tr>
            </thead>
            <tbody>
              {row.indicators.map((item) => (
                <tr key={item.metric_code}>
                  <td>{item.metric_code}</td>
                  <td>{item.value ?? "ไม่มีข้อมูล"}</td>
                  <td>{item.unit || "ไม่มีข้อมูล"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </details>
    </article>
  )
}
