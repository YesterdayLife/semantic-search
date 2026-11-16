const QUANTITY = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 3 })

export function formatQuantity(value: number | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "ไม่มีข้อมูล"
  const formatted = QUANTITY.format(value)
  return unit ? `${formatted} ${unit}` : formatted
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "ไม่มีข้อมูล"
  return value.toFixed(4)
}

export function formatMilliseconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "ไม่มีข้อมูล"
  return `${QUANTITY.format(value)} ms`
}

export function formatMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toFixed(4)
}

export function presentEligibility(reason: string): string {
  return reason.replace(/(\d+(?:\.\d+)?)[eE][+-]?\d+/g, (token) => {
    const value = Number(token)
    if (!Number.isFinite(value)) return token
    const text = value.toFixed(6).replace(/\.?0+$/, "")
    return text || "0"
  })
}

export function timingTotal(timing: unknown): number | null {
  if (typeof timing === "number") return timing
  if (timing && typeof timing === "object" && "total" in timing) {
    const total = (timing as { total?: unknown }).total
    return typeof total === "number" ? total : null
  }
  return null
}
