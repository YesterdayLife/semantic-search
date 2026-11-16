import type { SearchResult } from "../api/types.ts"

export interface ProductionPoint {
  year: number
  quantity: number
  unit: string
  crop: string
  spatialLevel: string
  source: string
}

export interface ProductionSeries {
  unit: string
  crop: string
  spatialLevel: string
  source: string
  points: ProductionPoint[]
}

/** Chart only a single crop, unit, spatial level, and source. Never sum duplicate years. */
export function productionSeries(rows: SearchResult[]): ProductionSeries | null {
  const usable = rows.filter((row) => row.answers_requested_measure !== false)
  if (!usable.length) return null
  const points: ProductionPoint[] = []
  for (const row of usable) {
    const quantity = row.production_quantity
    const unit = row.production_unit
    const year = row.year?.year_ce
    const crop = row.crop?.crop_id
    const spatialLevel = row.spatial_level
    const source = row.source?.source_id
    if (quantity === null || quantity === undefined || !unit || year === null || year === undefined || !crop || !spatialLevel || !source) {
      return null
    }
    points.push({ year, quantity, unit, crop, spatialLevel, source })
  }
  const [first] = points
  if (!first) return null
  const sameGroup = points.every(
    (point) => point.unit === first.unit && point.crop === first.crop && point.spatialLevel === first.spatialLevel && point.source === first.source,
  )
  if (!sameGroup) return null
  const years = points.map((point) => point.year)
  if (new Set(years).size !== years.length) return null
  return {
    unit: first.unit,
    crop: first.crop,
    spatialLevel: first.spatialLevel,
    source: first.source,
    points: [...points].sort((left, right) => left.year - right.year),
  }
}
