import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { ProductionSeries } from "../lib/charts.ts"
import { formatQuantity } from "../lib/format.ts"

const LEVEL: Record<string, string> = { country: "ระดับประเทศ", region: "ระดับภาค" }

export function ProductionChart({ series }: { series: ProductionSeries }) {
  const data = series.points.map((point) => ({ year: point.year, quantity: point.quantity }))
  return (
    <section className="chart-panel" aria-label="กราฟผลผลิต">
      <h3>
        ผลผลิต {series.crop} · {LEVEL[series.spatialLevel] ?? series.spatialLevel} · {series.source}
      </h3>
      <p>หน่วยแกนตั้งคือ {series.unit} จาก SQLite ไม่ได้รวมหลายแหล่งข้อมูล</p>
      <div className="chart-frame">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="year" label={{ value: "ปี ค.ศ.", position: "insideBottom", offset: -2 }} />
            <YAxis label={{ value: series.unit, angle: -90, position: "insideLeft" }} />
            <Tooltip formatter={(value) => formatQuantity(Number(value), series.unit)} />
            <Bar dataKey="quantity" fill="#0f766e" name={`ผลผลิต (${series.unit})`} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table>
        <caption>ค่าที่ใช้วาดกราฟ</caption>
        <thead>
          <tr>
            <th>ปี</th>
            <th>ปริมาณ</th>
          </tr>
        </thead>
        <tbody>
          {series.points.map((point) => (
            <tr key={point.year}>
              <td>{point.year}</td>
              <td>{formatQuantity(point.quantity, point.unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
