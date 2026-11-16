import type { CatalogPayload, NumericConstraint, SearchMode } from "../api/types.ts"
import { unitForMetric, type FilterDraft, type NumericDraft } from "../api/requests.ts"

const SEASON_LABEL: Record<string, string> = { all: "ทั้งหมด", dry: "ฤดูแล้ง", wet: "ฤดูฝน" }
const LEVEL_LABEL: Record<string, string> = { country: "ประเทศ", region: "ภาค" }
const METRIC_LABEL: Record<NumericConstraint["metric"], string> = {
  production: "ผลผลิต",
  yield_harvested: "ผลผลิตต่อไร่ที่เก็บเกี่ยว",
  yield_planted: "ผลผลิตต่อไร่ที่ปลูก",
  area_harvested: "พื้นที่เก็บเกี่ยว",
  area_planted: "พื้นที่ปลูก",
}
const OPERATOR_LABEL: Record<NumericConstraint["operator"], string> = {
  gt: "มากกว่า",
  gte: "อย่างน้อย",
  lt: "น้อยกว่า",
  lte: "ไม่เกิน",
}

interface SearchFiltersProps {
  mode: SearchMode
  catalog: CatalogPayload | null
  filters: FilterDraft
  numeric: NumericDraft
  onFilters: (filters: FilterDraft) => void
  onNumeric: (numeric: NumericDraft) => void
}

export function SearchFilters({ mode, catalog, filters, numeric, onFilters, onNumeric }: SearchFiltersProps) {
  function setFilter(key: keyof FilterDraft, value: string) {
    onFilters({ ...filters, [key]: value })
  }

  function setMetric(metric: NumericConstraint["metric"]) {
    onNumeric({ ...numeric, metric, unit: unitForMetric(metric) })
  }

  return (
    <fieldset className="filters">
      <legend>ตัวกรองจากฐานข้อมูล</legend>
      {mode === "dictionary" ? (
        <p className="note">โหมด Dictionary ใช้ตัวแยกคำของคำค้นเท่านั้น ตัวกรองที่เลือกจะไม่ถูกส่งเข้า SQL ของพจนานุกรม</p>
      ) : null}
      <div className="filter-grid">
        <label>
          พืช
          <select aria-label="พืช" value={filters.crop_id} onChange={(event) => setFilter("crop_id", event.target.value)}>
            <option value="">ไม่ระบุ</option>
            {(catalog?.crops ?? []).map((crop) => (
              <option key={crop.crop_id} value={crop.crop_id}>
                {crop.crop_name} ({crop.crop_id})
              </option>
            ))}
          </select>
        </label>
        <label>
          ปี ค.ศ.
          <select aria-label="ปี" value={filters.year_ce} onChange={(event) => setFilter("year_ce", event.target.value)}>
            <option value="">ไม่ระบุ</option>
            {(catalog?.years ?? []).map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
        <label>
          ภาค
          <select aria-label="ภาค" value={filters.region_code} onChange={(event) => setFilter("region_code", event.target.value)}>
            <option value="">ไม่ระบุ</option>
            {(catalog?.regions ?? []).map((region) => (
              <option key={region.region_code} value={region.region_code}>
                {region.region_name} ({region.region_code})
              </option>
            ))}
          </select>
        </label>
        <label>
          ฤดู
          <select aria-label="ฤดู" value={filters.season} onChange={(event) => setFilter("season", event.target.value)}>
            <option value="">ไม่ระบุ</option>
            {(catalog?.seasons ?? []).map((season) => (
              <option key={season} value={season}>
                {SEASON_LABEL[season] ?? season}
              </option>
            ))}
          </select>
        </label>
        <label>
          ระดับพื้นที่
          <select aria-label="ระดับพื้นที่" value={filters.spatial_level} onChange={(event) => setFilter("spatial_level", event.target.value)}>
            <option value="">ไม่ระบุ</option>
            {(catalog?.spatial_levels ?? []).map((level) => (
              <option key={level} value={level}>
                {LEVEL_LABEL[level] ?? level}
              </option>
            ))}
          </select>
        </label>
        <label>
          แหล่งข้อมูล
          <select aria-label="แหล่งข้อมูล" value={filters.source_id} onChange={(event) => setFilter("source_id", event.target.value)}>
            <option value="">ไม่ระบุ</option>
            {(catalog?.sources ?? []).map((source) => (
              <option key={source.source_id} value={source.source_id}>
                {source.agency} · {source.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      {mode === "hybrid" ? (
        <div className="numeric">
          <label className="check">
            <input
              type="checkbox"
              checked={numeric.enabled}
              onChange={(event) => onNumeric({ ...numeric, enabled: event.target.checked })}
            />
            ใช้เงื่อนไขตัวเลขจาก SQLite
          </label>
          <label>
            ตัวชี้วัด
            <select
              aria-label="ตัวชี้วัดตัวเลข"
              value={numeric.metric}
              onChange={(event) => setMetric(event.target.value as NumericConstraint["metric"])}
            >
              {(catalog?.numeric_metrics ?? [{ metric: "production", unit: "t" }]).map((item) => (
                <option key={item.metric} value={item.metric}>
                  {METRIC_LABEL[item.metric]}
                </option>
              ))}
            </select>
          </label>
          <label>
            ตัวดำเนินการ
            <select
              aria-label="ตัวดำเนินการ"
              value={numeric.operator}
              onChange={(event) => onNumeric({ ...numeric, operator: event.target.value as NumericConstraint["operator"] })}
            >
              {(catalog?.numeric_operators ?? ["gt", "gte", "lt", "lte"]).map((operator) => (
                <option key={operator} value={operator}>
                  {OPERATOR_LABEL[operator]} ({operator})
                </option>
              ))}
            </select>
          </label>
          <label>
            ค่าขีดจำกัด
            <input
              aria-label="ค่าขีดจำกัด"
              inputMode="decimal"
              value={numeric.threshold}
              onChange={(event) => onNumeric({ ...numeric, threshold: event.target.value })}
            />
          </label>
          <p className="unit-lock">
            หน่วยที่ส่งไปยัง API: <strong>{unitForMetric(numeric.metric)}</strong>
          </p>
        </div>
      ) : (
        <p className="note">เงื่อนไขตัวเลขถูกส่งเฉพาะโหมด Hybrid และใช้หน่วยตามที่เก็บใน SQLite</p>
      )}
    </fieldset>
  )
}
