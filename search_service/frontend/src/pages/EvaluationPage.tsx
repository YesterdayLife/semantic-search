import { useEffect, useState } from "react"
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { SearchClient } from "../api/client.ts"
import type { EvaluationReport, MetricBlock } from "../api/types.ts"
import { formatMetric, formatMilliseconds } from "../lib/format.ts"
import { translateMessage } from "../lib/messages.ts"
import { metricChartPoints } from "../lib/metrics.ts"

const METHODS = ["dictionary", "semantic", "hybrid"] as const

export function EvaluationPage({ client }: { client: SearchClient }) {
  const [report, setReport] = useState<EvaluationReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    client
      .evaluation()
      .then((payload) => {
        if (active) setReport(payload)
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "ไม่พบรายงานการประเมิน")
      })
    return () => {
      active = false
    }
  }, [client])

  if (error) return <p className="warning" role="alert">{error}</p>
  if (!report) return <p className="loading">กำลังโหลดรายงานที่บันทึกไว้</p>
  const chartData = metricChartPoints(METHODS, (method) => report.backends?.[method]?.aggregate)
  return (
    <section className="page evaluation">
      <h2>แดชบอร์ดการประเมิน</h2>
      <p className="note">{translateMessage(report.report_note ?? "")}</p>
      <p>ชุดข้อมูล {report.query_count ?? "—"} คำค้น · top-k {report.top_k ?? "—"} · วิธีที่ประเมิน: Dictionary, Semantic, Hybrid</p>
      <p className="note">
        Precision@5 ในโครงการนี้ใช้ตัวส่วนเป็นจำนวนแถวคำตอบที่ส่งกลับ ไม่ได้หารด้วย K เสมอไป
        {report.policy?.precision_denominator ? ` (${translateMessage(report.policy.precision_denominator)})` : ""}
      </p>
      <div className="metric-grid">
        {METHODS.map((method) => (
          <MetricCard key={method} title={method} phase="Phase 7 ทั้งชุด" block={report.backends?.[method]?.aggregate} />
        ))}
      </div>
      <h3>Phase 6 subset</h3>
      <div className="metric-grid">
        {METHODS.map((method) => (
          <MetricCard key={`${method}-p6`} title={method} phase="คำค้นเดิม 45 ข้อ" block={report.backends?.[method]?.phase6_subset} />
        ))}
      </div>
      <section className="chart-panel" data-testid="metric-chart">
        <h3>Precision@5 และ Recall@5 จากรายงาน</h3>
        <p>ค่าเหล่านี้เป็นคะแนนการประเมิน ไม่ใช่ปริมาณผลผลิต</p>
        <div className="chart-frame">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="method" />
              <YAxis domain={[0, 1]} />
              <Tooltip />
              <Legend />
              <Bar dataKey="precision" fill="#1f7a4d" name="Precision@5" />
              <Bar dataKey="recall" fill="#0f766e" name="Recall@5" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <table>
          <caption>ค่าในกราฟ</caption>
          <thead>
            <tr>
              <th>วิธี</th>
              <th>Precision@5</th>
              <th>Recall@5</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map((row) => (
              <tr key={row.method}>
                <td>{row.method}</td>
                <td>{formatMetric(row.precision)}</td>
                <td>{formatMetric(row.recall)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section>
        <h3>เวลาจากเบนช์มาร์กที่บันทึกไว้</h3>
        <p className="note">ตัวเลขนี้ไม่ใช่การวัดระบบสดในขณะเปิดหน้านี้</p>
        <table>
          <thead>
            <tr>
              <th>ช่วง</th>
              <th>ค่าเฉลี่ย</th>
              <th>มัธยฐาน</th>
              <th>p95</th>
            </tr>
          </thead>
          <tbody>
            <LatencyRow label="Dictionary warm" stats={report.benchmark?.dictionary_warm} />
            <LatencyRow label="Semantic warm" stats={report.benchmark?.semantic_warm} />
            <LatencyRow label="Hybrid warm" stats={report.benchmark?.hybrid_warm} />
            <LatencyRow label="Compare warm" stats={report.benchmark?.compare_warm} />
          </tbody>
        </table>
        <p>เวลาโหลดโมเดล: {formatMilliseconds(report.benchmark?.model_initialization_ms)} · ทำซ้ำ {report.benchmark?.repetitions ?? "—"} ครั้ง</p>
      </section>
    </section>
  )
}

function MetricCard({ title, phase, block }: { title: string; phase: string; block: MetricBlock | undefined }) {
  return (
    <article className="metric-card">
      <h3>{title}</h3>
      <p>{phase}</p>
      <dl>
        <div><dt>Precision@5</dt><dd>{formatMetric(block?.precision_at_k)}</dd></div>
        <div><dt>Recall@5</dt><dd>{formatMetric(block?.recall_at_k)}</dd></div>
        <div><dt>Hit Rate@5</dt><dd>{formatMetric(block?.hit_at_k)}</dd></div>
        <div><dt>MRR</dt><dd>{formatMetric(block?.mrr)}</dd></div>
        <div><dt>nDCG@5</dt><dd>{formatMetric(block?.ndcg_at_k)}</dd></div>
        <div><dt>Multi-crop coverage</dt><dd>{formatMetric(block?.crop_coverage)}</dd></div>
        <div><dt>Numeric correctness</dt><dd>{formatMetric(block?.numeric_condition_correctness)}</dd></div>
      </dl>
    </article>
  )
}

function LatencyRow({ label, stats }: { label: string; stats?: { mean_ms?: number; median_ms?: number; p95_ms?: number } }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{formatMilliseconds(stats?.mean_ms)}</td>
      <td>{formatMilliseconds(stats?.median_ms)}</td>
      <td>{formatMilliseconds(stats?.p95_ms)}</td>
    </tr>
  )
}
