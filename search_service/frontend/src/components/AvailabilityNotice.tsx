import { AlertTriangle } from "lucide-react"
import type { Availability } from "../api/types.ts"

const COPY: Record<string, { title: string; body: string }> = {
  supported: {
    title: "รองรับตัวชี้วัดที่ขอ",
    body: "แถวคำตอบเป็นปริมาณผลผลิตจาก SQLite",
  },
  partially_supported: {
    title: "รองรับบางส่วน",
    body: "คำถามมีส่วนที่ฐานข้อมูลไม่มี เช่น ปุ๋ย น้ำ พลังงาน หรือคาร์บอนฟุตพรินต์ แถวที่แสดงเป็นผลผลิตเพื่อเป็นบริบท และไม่ใช่คำตอบของตัวชี้วัดนั้น",
  },
  unsupported: {
    title: "ไม่พบตัวชี้วัดที่ขอในฐานข้อมูล",
    body: "ระบบไม่มีปริมาณปุ๋ย น้ำ พลังงาน หรือคาร์บอนฟุตพรินต์ จึงไม่แสดงผลผลิตเป็นคำตอบของคำถามนี้",
  },
}

export function AvailabilityNotice({ status }: { status: Availability | null | undefined }) {
  if (!status) return null
  const copy = COPY[status] ?? { title: status, body: "สถานะนี้มาจากการตอบกลับของ API" }
  return (
    <aside className={`notice notice-${status}`} role="status">
      <AlertTriangle size={18} aria-hidden="true" />
      <div>
        <strong>{copy.title}</strong>
        <p>{copy.body}</p>
      </div>
    </aside>
  )
}
