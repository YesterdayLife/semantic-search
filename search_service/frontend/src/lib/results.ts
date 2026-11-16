import type { Availability, FilterSet, SearchResult, SemanticPayload } from "../api/types.ts"

export interface RowGroups {
  answers: SearchResult[]
  context: SearchResult[]
}

export function semanticAvailability(payload: SemanticPayload): Availability {
  const measures = payload.unavailable_measures ?? []
  if (!measures.length) return "supported"
  const scoped = Object.values(payload.parsed_filters ?? {}).some((value) => value !== null && value !== undefined)
  return scoped ? "partially_supported" : "unsupported"
}

export function splitRows(rows: SearchResult[] | undefined, contextRows: SearchResult[] | undefined, availability: Availability): RowGroups {
  const answers: SearchResult[] = []
  const context = [...(contextRows ?? [])]
  for (const row of rows ?? []) {
    if (availability === "unsupported" || row.answers_requested_measure === false) context.push(row)
    else answers.push(row)
  }
  return { answers, context }
}

export function filterSummary(filters: FilterSet | undefined): string[] {
  if (!filters) return []
  return Object.entries(filters)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}=${String(value)}`)
}

export const EXAMPLES = [
  "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
  "maize production in central Thailand 2022",
  "ข้าวนาปรังปี 2565",
  "มันสำปะหลังและข้าวโพด",
  "ผลผลิตมากกว่า 1,000,000 ตัน",
  "มันสำปะหลังภาคใต้ปี 2566",
  "carbon footprint of rice production",
  "ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง",
]
