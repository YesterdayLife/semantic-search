import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import App from "./App.tsx"
import { ApiError, type SearchClient } from "./api/client.ts"
import { planRequest } from "./api/requests.ts"
import type { CatalogPayload, ComparePayload, EvaluationReport, HybridPayload, SearchResult } from "./api/types.ts"
import { ProductionChart } from "./components/ProductionChart.tsx"
import { formatQuantity, presentEligibility } from "./lib/format.ts"
import { productionSeries } from "./lib/charts.ts"
import { translateMessage } from "./lib/messages.ts"
import { metricChartPoints } from "./lib/metrics.ts"
import { ComparePage } from "./pages/ComparePage.tsx"
import { EvaluationPage } from "./pages/EvaluationPage.tsx"
import { SearchPage } from "./pages/SearchPage.tsx"

const catalog: CatalogPayload = {
  crops: [{ crop_id: "CAS", crop_name: "มันสำปะหลัง" }, { crop_id: "MAI", crop_name: "ข้าวโพดเลี้ยงสัตว์" }],
  regions: [{ region_code: "NOR", region_name: "เหนือ" }],
  seasons: ["all", "dry", "wet"],
  spatial_levels: ["country", "region"],
  sources: [{ source_id: "SRC-06", agency: "OAE", title: "OAE cassava" }],
  years: [2023],
  process_count: 105,
  numeric_metrics: [
    { metric: "production", unit: "t" },
    { metric: "yield_harvested", unit: "kg/rai" },
  ],
  numeric_operators: ["gt", "gte", "lt", "lte"],
}

function row(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    process_id: "P-CAS",
    crop: { crop_id: "CAS", crop_name: "มันสำปะหลัง" },
    year: { year_ce: 2023 },
    region: { region_code: "NOR", region_name: "เหนือ" },
    season: "all",
    spatial_level: "region",
    production_quantity: 7707851,
    production_unit: "t",
    source: { source_id: "SRC-06", agency: "OAE", title: "OAE cassava" },
    similarity_score: 0.8123,
    answers_requested_measure: true,
    ...overrides,
  }
}

function hybrid(overrides: Partial<HybridPayload> = {}): HybridPayload {
  return {
    query: "มันสำปะหลัง",
    search_mode: "hybrid",
    availability_status: "supported",
    count: 1,
    eligible_count: 1,
    results: [row()],
    context_results: [],
    warnings: [],
    unapplied_conditions: [],
    applied_filters: { crop_ids: ["CAS"] },
    ranking_method: "eligibility-first-bge-m3",
    timing_ms: { total: 12.5 },
    ...overrides,
  }
}

function client(partial: Partial<SearchClient> = {}): SearchClient {
  return {
    health: vi.fn(async () => ({ status: "ok" })),
    ready: vi.fn(async () => ({ status: "ready" })),
    catalog: vi.fn(async () => catalog),
    evaluation: vi.fn(async () => report),
    search: vi.fn(),
    compare: vi.fn(),
    hybrid: vi.fn(async () => hybrid()),
    ...partial,
  }
}

const report: EvaluationReport = {
  query_count: 61,
  top_k: 5,
  policy: { precision_denominator: "number of answer rows returned, at most k" },
  report_note: "saved report",
  backends: {
    dictionary: { aggregate: { precision_at_k: 0.8923, recall_at_k: 0.5251, hit_at_k: 1, mrr: 0.9402, ndcg_at_k: 0.8976, crop_coverage: 0.6, numeric_condition_correctness: 0 }, phase6_subset: { precision_at_k: 1, recall_at_k: 0.6486 } },
    semantic: { aggregate: { precision_at_k: 0.8641, recall_at_k: 0.5166, hit_at_k: 0.9744, mrr: 0.909, ndcg_at_k: 0.8746 }, phase6_subset: { precision_at_k: 1, recall_at_k: 0.6486 } },
    hybrid: { aggregate: { precision_at_k: 1, recall_at_k: 0.5849, hit_at_k: 1, mrr: 1, ndcg_at_k: 1, crop_coverage: 1, numeric_condition_correctness: 1 }, phase6_subset: { precision_at_k: 1, recall_at_k: 0.6486 } },
  },
  benchmark: {
    repetitions: 5,
    model_initialization_ms: 1930.796,
    dictionary_warm: { mean_ms: 0.545, median_ms: 0.676, p95_ms: 1.026 },
    semantic_warm: { mean_ms: 188.975, median_ms: 184.015, p95_ms: 216.253 },
    hybrid_warm: { mean_ms: 115.719, median_ms: 177.434, p95_ms: 185.573 },
  },
}

const comparePayload: ComparePayload = {
  query: "มันสำปะหลัง",
  score_comparison: null,
  note: "Dictionary match reasons and semantic similarity scores are separate",
  filter_comparability: { directly_comparable: true, reasons: [] },
  dictionary: {
    availability_status: "supported",
    timing_ms: 0.7,
    results: [row({ similarity_score: null, match_reason: "dictionary:crop_id=CAS" })],
    context_results: [],
    warnings: [],
  },
  semantic: {
    availability_status: "supported",
    timing_ms: 180,
    results: [row()],
    context_results: [],
    warnings: [],
  },
}

describe("frontend", () => {
  it("T01 renders the application", async () => {
    render(<App client={client()} />)
    expect(await screen.findByRole("heading", { name: "ค้นหาเชิงความหมาย" })).toBeInTheDocument()
  })

  it("T02 updates the search input", async () => {
    const user = userEvent.setup()
    render(<SearchPage client={client()} catalog={catalog} />)
    const input = screen.getByLabelText("คำค้น")
    await user.type(input, "ข้าว")
    expect(input).toHaveValue("ข้าว")
  })

  it("T03 switches search mode", async () => {
    const user = userEvent.setup()
    render(<SearchPage client={client()} catalog={catalog} />)
    const semantic = screen.getByRole("radio", { name: /^Semantic/ })
    await user.click(semantic)
    expect(semantic).toBeChecked()
    expect(screen.getByRole("radio", { name: /^Hybrid/ })).not.toBeChecked()
  })

  it("T04 builds a hybrid request", async () => {
    const user = userEvent.setup()
    const api = client()
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "มันสำปะหลังและข้าวโพด")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(api.hybrid).toHaveBeenCalledWith(
      { query: "มันสำปะหลังและข้าวโพด", top_k: 5 },
      expect.any(AbortSignal),
    )
  })

  it("T05 submits structured filters", async () => {
    const user = userEvent.setup()
    const api = client()
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "ผลผลิต")
    await user.selectOptions(screen.getByLabelText("พืช"), "CAS")
    await user.selectOptions(screen.getByLabelText("ปี"), "2023")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(api.hybrid).toHaveBeenCalledWith(
      { query: "ผลผลิต", top_k: 5, filters: { crop_id: "CAS", year_ce: 2023 } },
      expect.any(AbortSignal),
    )
  })

  it("T06 shows a loading state and ignores a second click", async () => {
    const user = userEvent.setup()
    let release: (value: HybridPayload) => void = () => undefined
    const api = client({
      hybrid: vi.fn(() => new Promise<HybridPayload>((resolve) => {
        release = resolve
      })),
    })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "ข้าว")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    const busy = screen.getByRole("button", { name: "กำลังค้นหา" })
    expect(busy).toHaveAttribute("aria-busy", "true")
    await user.click(busy)
    expect(api.hybrid).toHaveBeenCalledTimes(1)
    release(hybrid())
  })

  it("T07 shows HTTP 422", async () => {
    const user = userEvent.setup()
    const api = client({ hybrid: vi.fn(async () => Promise.reject(new ApiError(422, "invalid_request", "The request is invalid."))) })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "ข้าว")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 422")
  })

  it("T08 shows HTTP 503", async () => {
    const user = userEvent.setup()
    const api = client({ hybrid: vi.fn(async () => Promise.reject(new ApiError(503, "qdrant_unavailable", "Qdrant is unavailable"))) })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "ข้าว")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503")
  })

  it("T09 renders a SQLite-backed result", async () => {
    const user = userEvent.setup()
    render(<SearchPage client={client()} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "มันสำปะหลัง")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByRole("heading", { name: "มันสำปะหลัง" })).toBeInTheDocument()
    expect(screen.getByText("P-CAS")).toBeInTheDocument()
  })

  it("T10 formats quantities without turning them into scores", () => {
    expect(formatQuantity(1000000, "t")).toContain("t")
    expect(formatQuantity(1000000, "t")).not.toContain("cosine")
  })

  it("T11 preserves the SQLite unit", () => {
    expect(formatQuantity(12.5, "kg/rai")).toMatch(/kg\/rai$/)
    expect(formatQuantity(12.5, "rai")).toMatch(/rai$/)
  })

  it("T12 warns for an unsupported measurement and shows no answer row", async () => {
    const user = userEvent.setup()
    const api = client({
      hybrid: vi.fn(async () => hybrid({
        availability_status: "unsupported",
        count: 0,
        results: [],
        requested_measure: ["fertilizer"],
      })),
    })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "ปุ๋ย")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByText("ไม่พบตัวชี้วัดที่ขอในฐานข้อมูล")).toBeInTheDocument()
    expect(screen.getByText("ไม่มีแถวคำตอบ เพราะฐานข้อมูลไม่มีตัวชี้วัดที่ขอ")).toBeInTheDocument()
    expect(screen.queryByText("7707851")).not.toBeInTheDocument()
  })

  it("T13 separates context-only records", async () => {
    const user = userEvent.setup()
    const api = client({
      hybrid: vi.fn(async () => hybrid({
        availability_status: "partially_supported",
        results: [row({ answers_requested_measure: false, production_quantity: 431024 })],
      })),
    })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "ปุ๋ยมันสำปะหลัง")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByRole("heading", { name: "ระเบียนบริบท ไม่ใช่คำตอบของตัวชี้วัดที่ขอ" })).toBeInTheDocument()
    expect(screen.getByText("ไม่ใช่คำตอบของตัวชี้วัดที่ขอ")).toBeInTheDocument()
  })

  it("T14 renders both comparison columns", async () => {
    const user = userEvent.setup()
    const api = client({ compare: vi.fn(async () => comparePayload) })
    render(<ComparePage client={api} catalog={catalog} />)
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByRole("heading", { name: "Dictionary Search" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "BGE-M3 Semantic Search" })).toBeInTheDocument()
  })

  it("T15 keeps dictionary reasons separate from cosine scores", async () => {
    const user = userEvent.setup()
    const api = client({ compare: vi.fn(async () => comparePayload) })
    render(<ComparePage client={api} catalog={catalog} />)
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByText("คอลัมน์นี้แสดงเหตุผลการจับคู่ ไม่ใช่ cosine")).toBeInTheDocument()
    expect(screen.getByText("คอลัมน์นี้แสดง cosine similarity ไม่ใช่ปริมาณผลผลิต")).toBeInTheDocument()
    expect(screen.getByText(/dictionary:crop_id=CAS/)).toBeInTheDocument()
  })

  it("T16 displays saved evaluation metrics", async () => {
    render(<EvaluationPage client={client()} />)
    expect((await screen.findAllByText("0.8923")).length).toBeGreaterThan(0)
    expect(screen.getByText(/61/)).toBeInTheDocument()
    expect(screen.getByText(/ไม่ได้หารด้วย K เสมอไป/)).toBeInTheDocument()
    expect(screen.getByText(/ไม่ใช่การวัดระบบสด/)).toBeInTheDocument()
  })

  it("T17 charts the actual production values", () => {
    const series = productionSeries([row({ production_quantity: 7707851 }), row({ process_id: "P-2", year: { year_ce: 2022 }, production_quantity: 1204100 })])
    expect(series?.points.map((point) => point.quantity)).toEqual([1204100, 7707851])
    render(<ProductionChart series={series!} />)
    expect(screen.getByText(formatQuantity(7707851, "t"))).toBeInTheDocument()
    expect(screen.getByText(/หน่วยแกนตั้งคือ t/)).toBeInTheDocument()
  })

  it("T18 shows an empty result state", async () => {
    const user = userEvent.setup()
    const api = client({ hybrid: vi.fn(async () => hybrid({ count: 0, eligible_count: 0, results: [], availability_status: "supported" })) })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "มันสำปะหลังภาคใต้ปี 2566")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByText("ไม่พบระเบียนที่ตรงกับเงื่อนไข")).toBeInTheDocument()
  })

  it("T19 shows missing quantities as unavailable", async () => {
    const user = userEvent.setup()
    const api = client({ hybrid: vi.fn(async () => hybrid({ results: [row({ production_quantity: null, production_unit: null })] })) })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "มันสำปะหลัง")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect((await screen.findAllByText("ไม่มีข้อมูล")).length).toBeGreaterThan(0)
    expect(screen.queryByText(/^0 t$/)).not.toBeInTheDocument()
  })

  it("T20 includes a mobile layout rule", () => {
    const css = readFileSync(resolve("src/styles/app.css"), "utf8")
    expect(css).toContain("@media (max-width: 760px)")
    expect(css).toContain("grid-template-columns: 1fr")
  })

  it("keeps numeric identity in the hybrid request", () => {
    const planned = planRequest(
      "hybrid",
      "ผลผลิต",
      5,
      { crop_id: "CAS", year_ce: "", region_code: "", season: "", spatial_level: "", source_id: "" },
      { enabled: true, metric: "production", operator: "gt", threshold: "1000000", unit: "kg/rai" },
    )
    expect(planned.path).toBe("/hybrid-search")
    expect(planned.body).toMatchObject({ numeric: { metric: "production", operator: "gt", threshold: 1000000, unit: "t" } })
  })

  it("translates known warnings and keeps unknown warnings", async () => {
    const user = userEvent.setup()
    const api = client({
      hybrid: vi.fn(async () => hybrid({
        warnings: [
          "Year 2566 was converted from Buddhist Era to 2023 CE.",
          "A custom diagnostic that has no translation.",
        ],
      })),
    })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "มันสำปะหลัง")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByText("แปลงปี พ.ศ. 2566 เป็น ค.ศ. 2023")).toBeInTheDocument()
    expect(screen.getByText("A custom diagnostic that has no translation.")).toBeInTheDocument()
    expect(translateMessage("region_code cannot be combined with spatial_level country")).toContain("รหัสภาค")
  })

  it("clears stale results when the mode changes and ignores the old response", async () => {
    const user = userEvent.setup()
    let release: (value: HybridPayload) => void = () => undefined
    const api = client({
      hybrid: vi.fn(() => new Promise<HybridPayload>((resolve) => {
        release = resolve
      })),
    })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.type(screen.getByLabelText("คำค้น"), "มันสำปะหลัง")
    await user.selectOptions(screen.getByLabelText("พืช"), "CAS")
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    await user.click(screen.getByRole("radio", { name: /^Semantic/ }))
    expect(screen.queryByRole("heading", { name: "มันสำปะหลัง" })).not.toBeInTheDocument()
    expect(screen.getByLabelText("คำค้น")).toHaveValue("มันสำปะหลัง")
    expect(screen.getByLabelText("พืช")).toHaveValue("CAS")
    await act(async () => {
      release(hybrid())
    })
    expect(screen.queryByRole("heading", { name: "มันสำปะหลัง" })).not.toBeInTheDocument()
  })

  it("keeps a measured zero and omits a null metric from the chart", async () => {
    const api = client({
      evaluation: vi.fn(async () => ({
        ...report,
        report_note: "Values are read from the saved evaluation report. This request does not rerun the evaluation.",
        backends: {
          dictionary: { aggregate: { precision_at_k: null, recall_at_k: 0, numeric_condition_correctness: 0 } },
          semantic: { aggregate: { precision_at_k: null, recall_at_k: null } },
          hybrid: { aggregate: { precision_at_k: 1, recall_at_k: 0.5 } },
        },
      })),
    })
    render(<EvaluationPage client={api} />)
    const table = await screen.findByRole("table", { name: "ค่าในกราฟ" })
    const rows = within(table).getAllByRole("row")
    const labels = rows.map((item) => item.textContent ?? "")
    expect(labels.some((text) => text.includes("dictionary") && text.includes("—") && text.includes("0.0000"))).toBe(true)
    expect(labels.some((text) => text.includes("semantic"))).toBe(false)
    expect(screen.getByText("ค่าเหล่านี้มาจากรายงานที่บันทึกไว้ ระบบไม่ได้ประเมินใหม่ในคำขอนี้")).toBeInTheDocument()
    expect(metricChartPoints(["dictionary"], () => ({ precision_at_k: null, recall_at_k: 0 }))).toEqual([{ method: "dictionary", recall: 0 }])
  })

  it("shows a dictionary source from the catalog and hides a missing source", async () => {
    const user = userEvent.setup()
    const api = client({
      compare: vi.fn(async () => ({
        ...comparePayload,
        dictionary: {
          ...comparePayload.dictionary,
          results: [row({ similarity_score: null, match_reason: "dictionary:crop_id=CAS", source: { source_id: "SRC-06", agency: null, title: null } })],
        },
        semantic: {
          ...comparePayload.semantic,
          results: [row({ process_id: "P-NO-SOURCE", source: null })],
        },
      })),
    })
    render(<ComparePage client={api} catalog={catalog} />)
    await user.click(screen.getByRole("button", { name: "ค้นหา" }))
    expect(await screen.findByText("แหล่งข้อมูล: OAE · OAE cassava")).toBeInTheDocument()
    expect(screen.getAllByText(/^แหล่งข้อมูล:/)).toHaveLength(1)
    expect(screen.queryByText("แหล่งข้อมูล: ไม่มีข้อมูล")).not.toBeInTheDocument()
  })

  it("prints a large threshold without scientific notation", () => {
    expect(presentEligibility("eligible:productiongt1e+07t")).toBe("eligible:productiongt10000000t")
    expect(presentEligibility("eligible:productiongt10000000t")).toBe("eligible:productiongt10000000t")
  })

  it("moves through search controls from the keyboard and announces loading", async () => {
    const user = userEvent.setup()
    let release: (value: HybridPayload) => void = () => undefined
    const api = client({
      hybrid: vi.fn(() => new Promise<HybridPayload>((resolve) => {
        release = resolve
      })),
    })
    render(<SearchPage client={api} catalog={catalog} />)
    await user.tab()
    const hybridMode = screen.getByRole("radio", { name: /^Hybrid/ })
    expect(hybridMode).toHaveFocus()
    await user.keyboard("{ArrowRight}")
    const semantic = screen.getByRole("radio", { name: /^Semantic/ })
    expect(semantic).toHaveFocus()
    expect(semantic).toBeChecked()
    await user.keyboard("{ArrowLeft}")
    expect(hybridMode).toHaveFocus()
    expect(hybridMode).toBeChecked()
    await user.tab()
    const query = screen.getByLabelText("คำค้น")
    expect(query).toHaveFocus()
    await user.tab({ shift: true })
    expect(hybridMode).toHaveFocus()
    await user.tab()
    await user.tab()
    expect(screen.getByLabelText("จำนวนผลลัพธ์")).toHaveFocus()
    await user.tab()
    const example = screen.getByRole("button", { name: "ผลผลิตมันสำปะหลังภาคเหนือปี 2566" })
    expect(example).toHaveFocus()
    expect(screen.getByRole("button", { name: "ค้นหา" })).toBeDisabled()
    await user.keyboard("{Enter}")
    expect(query).toHaveValue("ผลผลิตมันสำปะหลังภาคเหนือปี 2566")
    await user.keyboard("{Escape}")
    expect(query).toHaveValue("ผลผลิตมันสำปะหลังภาคเหนือปี 2566")
    await user.tab({ shift: true })
    expect(screen.getByRole("button", { name: "ค้นหา" })).toHaveFocus()
    await user.keyboard("{Enter}")
    expect(await screen.findByRole("status")).toHaveTextContent("กำลังค้นหา")
    await act(async () => {
      release(hybrid())
    })
    const summary = await screen.findByText("รายละเอียดทางเทคนิค")
    summary.focus()
    expect(summary).toHaveFocus()
    expect(summary.tagName).toBe("SUMMARY")
  })

  it("loads the evaluation dashboard on demand", async () => {
    const user = userEvent.setup()
    render(<App client={client()} />)
    expect(screen.queryByRole("heading", { name: "แดชบอร์ดการประเมิน" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "การประเมิน" }))
    expect(await screen.findByRole("heading", { name: "แดชบอร์ดการประเมิน" })).toBeInTheDocument()
    expect(await screen.findByRole("table", { name: "ค่าในกราฟ" })).toBeInTheDocument()
  })

  it("proxies the production preview to localhost", () => {
    const config = readFileSync(resolve("vite.config.ts"), "utf8")
    expect(config.match(/proxy: localApiProxy/g)).toHaveLength(2)
    expect(config).toContain('target: "http://127.0.0.1:8000"')
    expect(config).not.toContain("0.0.0.0")
  })
})
