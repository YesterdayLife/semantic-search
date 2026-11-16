import type { SearchMode } from "../api/types.ts"

const MODES: { id: SearchMode; label: string; detail: string }[] = [
  { id: "hybrid", label: "Hybrid", detail: "คัดกรองด้วย SQLite แล้วจัดอันดับด้วย BGE-M3" },
  { id: "semantic", label: "Semantic", detail: "BGE-M3 cosine บนคอลเลกชันเดิม" },
  { id: "dictionary", label: "Dictionary", detail: "ตัวแยกคำและ SQL ของพจนานุกรมเดิม" },
  { id: "compare", label: "Compare", detail: "แสดง Dictionary และ Semantic คู่กัน" },
]

interface SearchModeSelectorProps {
  mode: SearchMode
  onChange: (mode: SearchMode) => void
}

export function SearchModeSelector({ mode, onChange }: SearchModeSelectorProps) {
  return (
    <fieldset className="mode-selector">
      <legend>โหมดการค้นหา</legend>
      <div className="mode-grid">
        {MODES.map((item) => (
          <label key={item.id} className={mode === item.id ? "mode active" : "mode"}>
            <input
              type="radio"
              name="search-mode"
              value={item.id}
              checked={mode === item.id}
              onChange={() => onChange(item.id)}
            />
            <strong>{item.label}</strong>
            <span>{item.detail}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
