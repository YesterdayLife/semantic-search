interface StatusIndicatorProps {
  health: string
  ready: string
  readyLabel?: string
}

export function StatusIndicator({ health, ready, readyLabel = "โมเดล" }: StatusIndicatorProps) {
  const readyOk = ready === "ready"
  return (
    <p className="status" aria-live="polite">
      <span className={health === "ok" ? "dot ok" : "dot"} />
      API {health === "ok" ? "พร้อม" : health}
      <span className={readyOk ? "dot ok" : "dot"} />
      {readyLabel} {readyOk ? "พร้อม" : ready}
    </p>
  )
}
