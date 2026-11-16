export interface MetricChartPoint {
  method: string
  precision?: number
  recall?: number
}

export function metricChartPoints(
  methods: readonly string[],
  valueOf: (method: string) => { precision_at_k?: number | null; recall_at_k?: number | null } | undefined,
): MetricChartPoint[] {
  const points: MetricChartPoint[] = []
  for (const method of methods) {
    const block = valueOf(method)
    const precision = finite(block?.precision_at_k)
    const recall = finite(block?.recall_at_k)
    if (precision === undefined && recall === undefined) continue
    const point: MetricChartPoint = { method }
    if (precision !== undefined) point.precision = precision
    if (recall !== undefined) point.recall = recall
    points.push(point)
  }
  return points
}

function finite(value: number | null | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}
