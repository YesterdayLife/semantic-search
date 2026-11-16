const EXACT: Record<string, string> = {
  "The request is invalid.": "คำขอไม่ถูกต้อง",
  "Unknown search parameters were provided.": "มีพารามิเตอร์ที่ไม่รองรับ",
  "query must not be empty": "ต้องระบุคำค้น",
  "top_k must be an integer from 1 through 105": "จำนวนผลลัพธ์ต้องเป็นจำนวนเต็มตั้งแต่ 1 ถึง 105",
  "Unknown filter fields were provided.": "มีตัวกรองที่ไม่รองรับ",
  "One or more filters are invalid.": "ตัวกรองบางรายการไม่ถูกต้อง",
  "region_code cannot be combined with spatial_level country": "ไม่สามารถใช้รหัสภาคพร้อมกับระดับพื้นที่ประเทศ",
  "The numeric unit does not match the metric stored in SQLite.": "หน่วยตัวเลขไม่ตรงกับหน่วยที่เก็บใน SQLite",
  "Qdrant is unavailable": "Qdrant ไม่พร้อมให้บริการ",
  "SQLite is unavailable": "SQLite ไม่พร้อมให้บริการ",
  "Dictionary search is unavailable": "พจนานุกรมไม่พร้อมให้บริการ",
  "The search request could not be completed.": "ไม่สามารถทำการค้นหาได้",
  "Values are read from the saved evaluation report. This request does not rerun the evaluation.":
    "ค่าเหล่านี้มาจากรายงานที่บันทึกไว้ ระบบไม่ได้ประเมินใหม่ในคำขอนี้",
  "number of answer rows returned, at most k": "จำนวนแถวคำตอบที่ส่งกลับ สูงสุดไม่เกิน k",
  "Separate filters were not applied. Dictionary search used only its original query parser.":
    "ไม่ได้ใช้ตัวกรองที่เลือก พจนานุกรมใช้เฉพาะตัวแยกคำของคำค้น",
  "Separate filters were applied by semantic search only. Dictionary search used its original query parser, so the eligible record sets are not directly comparable.":
    "ตัวกรองถูกใช้เฉพาะฝั่ง Semantic พจนานุกรมใช้ตัวแยกคำเดิม จึงเปรียบเทียบชุดระเบียนตรงกันไม่ได้",
  "Dictionary match reasons and semantic similarity scores are separate and are not ranked against each other.":
    "เหตุผลของพจนานุกรมและคะแนน cosine แยกกัน และไม่ได้จัดอันดับร่วมกัน",
  "The two backends inferred different structured constraints, so they searched different eligible record sets.":
    "สองระบบตีความเงื่อนไขต่างกัน จึงค้นคนละชุดระเบียน",
  "The two backends assigned different availability statuses.": "สองระบบระบุสถานะความพร้อมของตัวชี้วัดต่างกัน",
  "Validated fertilizer quantities are not in this dataset. Any listed records are production output only.":
    "ชุดข้อมูลนี้ไม่มีปริมาณปุ๋ยที่ยืนยันแล้ว ระเบียนที่แสดงเป็นผลผลิตเท่านั้น",
  "Validated carbon-footprint values are not in this dataset. Any listed records are production output only.":
    "ชุดข้อมูลนี้ไม่มีคาร์บอนฟุตพรินต์ที่ยืนยันแล้ว ระเบียนที่แสดงเป็นผลผลิตเท่านั้น",
  "Validated energy-input quantities are not in this dataset. Any listed records are production output only.":
    "ชุดข้อมูลนี้ไม่มีปริมาณพลังงานที่ยืนยันแล้ว ระเบียนที่แสดงเป็นผลผลิตเท่านั้น",
  "Validated water-consumption quantities are not in this dataset. Any listed records are production output only.":
    "ชุดข้อมูลนี้ไม่มีปริมาณน้ำที่ยืนยันแล้ว ระเบียนที่แสดงเป็นผลผลิตเท่านั้น",
  "Qdrant did not return every eligible process, so only the returned eligible rows were ranked.":
    "Qdrant ไม่ได้ส่งคืนทุกระเบียนที่เข้าเกณฑ์ จึงจัดอันดับเฉพาะแถวที่ได้รับ",
  "The explicit numeric constraint overrides a comparison found in the query.": "เงื่อนไขตัวเลขที่เลือกทับค่าที่พบในคำค้น",
  "A process had more than one output quantity, so that quantity was omitted.": "ระเบียนมีปริมาณผลผลิตมากกว่าหนึ่งค่า จึงไม่แสดงปริมาณนั้น",
  "An eligible ranked id had no SQLite record and was omitted.": "รหัสที่จัดอันดับแล้วไม่มีระเบียนใน SQLite จึงตัดออก",
  "A ranked point had no SQLite record and was omitted.": "จุดที่จัดอันดับแล้วไม่มีระเบียนใน SQLite จึงตัดออก",
  "A ranked record did not satisfy the structured filters and was omitted.": "ระเบียนที่จัดอันดับไม่ตรงตัวกรอง จึงตัดออก",
  "The explicit crop_id filter overrides the crops inferred from the query.": "ตัวกรองพืชที่เลือกทับพืชที่อนุมานจากคำค้น",
  "The explicit year_ce filter overrides the year inferred from the query.": "ตัวกรองปีที่เลือกทับปีที่อนุมานจากคำค้น",
  "A country-level filter cleared the inferred region.": "ตัวกรองระดับประเทศล้างภาคที่อนุมานไว้",
  "The year is ambiguous, so no year filter was applied.": "ปีกำกวม จึงไม่ใช้ตัวกรองปี",
  "The year is outside the supported Common Era range, so no year filter was applied.": "ปีอยู่นอกช่วง ค.ศ. ที่รองรับ จึงไม่ใช้ตัวกรองปี",
  "The source is ambiguous, so no source filter was applied.": "แหล่งข้อมูลกำกวม จึงไม่ใช้ตัวกรองแหล่งข้อมูล",
}

const LABELS: Record<string, string> = {
  crop: "พืช",
  year: "ปี",
  region: "ภาค",
  season: "ฤดู",
  source: "แหล่งข้อมูล",
  spatial_level: "ระดับพื้นที่",
  crop_id: "พืช",
  year_ce: "ปี",
  region_code: "ภาค",
  source_id: "แหล่งข้อมูล",
}

function label(name: string): string {
  return LABELS[name] ?? name
}

export function translateMessage(message: string): string {
  const exact = EXACT[message]
  if (exact) return exact
  const patterns: Array<[RegExp, (...groups: string[]) => string]> = [
    [/^Year (\d+) was converted from Buddhist Era to (\d+) CE\.$/, (year, ce) => `แปลงปี พ.ศ. ${year} เป็น ค.ศ. ${ce}`],
    [/^Multiple crops were requested: (.+)\.$/, (crops) => `คำค้นขอหลายพืช: ${crops}`],
    [/^The year range (\d+) through (\d+) CE was applied\.$/, (from, to) => `ใช้ช่วงปี ค.ศ. ${from} ถึง ${to}`],
    [/^No eligible records exist for: (.+)\.$/, (crops) => `ไม่มีระเบียนที่เข้าเกณฑ์สำหรับ: ${crops}`],
    [/^top_k is smaller than the number of requested crops with data, so these crops were omitted: (.+)\.$/, (crops) => `จำนวนผลลัพธ์น้อยกว่าจำนวนพืชที่มีข้อมูล จึงไม่ได้แสดง: ${crops}`],
    [/^The explicit ([A-Za-z_]+) filter overrides the value inferred from the query\.$/, (key) => `ตัวกรอง${label(key)}ที่เลือกทับค่าที่อนุมานจากคำค้น`],
    [/^The ([A-Za-z_]+) is ambiguous, so no ([A-Za-z_]+) filter was applied\.$/, (name) => `${label(name)}กำกวม จึงไม่ใช้ตัวกรองนี้`],
    [/^The inferred ([A-Za-z_]+) is not present in the database, so it was not applied\.$/, (key) => `${label(key)}ที่อนุมานไม่มีในฐานข้อมูล จึงไม่ได้ใช้`],
  ]
  for (const [pattern, render] of patterns) {
    const match = message.match(pattern)
    if (match) return render(...match.slice(1))
  }
  return message
}

export function presentError(status: number, message: string): string {
  const text = translateMessage(message)
  if (status === 422) return `คำขอไม่ถูกต้อง (HTTP 422): ${text}`
  if (status === 503) return `บริการค้นหายังไม่พร้อม (HTTP 503): ${text}`
  return text
}
