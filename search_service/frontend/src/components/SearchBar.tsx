import type { FormEvent } from "react"
import { Search } from "lucide-react"
import { EXAMPLES } from "../lib/results.ts"

interface SearchBarProps {
  query: string
  topK: number
  loading: boolean
  onQueryChange: (value: string) => void
  onTopKChange: (value: number) => void
  onSubmit: () => void
  onExample: (value: string) => void
}

export function SearchBar({ query, topK, loading, onQueryChange, onTopKChange, onSubmit, onExample }: SearchBarProps) {
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!loading) onSubmit()
  }

  return (
    <form className="search-bar" onSubmit={submit}>
      <label className="field grow" htmlFor="search-query">
        <span>คำค้น</span>
        <input
          id="search-query"
          name="query"
          value={query}
          maxLength={500}
          placeholder="ค้นหาผลผลิตพืชเป็นภาษาไทยหรืออังกฤษ"
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </label>
      <label className="field topk" htmlFor="search-topk">
        <span>จำนวนผลลัพธ์</span>
        <select id="search-topk" value={topK} onChange={(event) => onTopKChange(Number(event.target.value))}>
          {[5, 10, 20].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <button className="primary" type="submit" disabled={loading || !query.trim()} aria-busy={loading}>
        <Search size={18} aria-hidden="true" />
        {loading ? "กำลังค้นหา" : "ค้นหา"}
      </button>
      <div className="examples" aria-label="ตัวอย่างคำค้น">
        {EXAMPLES.map((example) => (
          <button key={example} type="button" className="chip" onClick={() => onExample(example)}>
            {example}
          </button>
        ))}
      </div>
    </form>
  )
}
