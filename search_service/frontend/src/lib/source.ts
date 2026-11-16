export interface SourceMeta {
  source_id?: string | null
  agency?: string | null
  title?: string | null
}

export function sourceCaption(source: SourceMeta | null | undefined, catalog: SourceMeta[] = []): string | null {
  const sourceId = source?.source_id?.trim() ?? ""
  const known = catalog.find((item) => item.source_id === sourceId)
  const agency = source?.agency?.trim() || known?.agency?.trim() || ""
  const title = source?.title?.trim() || known?.title?.trim() || ""
  if (agency && title) return `${agency} · ${title}`
  if (agency || title) return agency || title
  if (sourceId) return sourceId
  return null
}
