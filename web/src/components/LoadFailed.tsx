import { useState } from "react"
import { RotateCwIcon, TriangleAlertIcon } from "lucide-react"

// Adapted from the React Bits Pro block empty-state-4: a failed-to-load
// state with what was requested, when, and a retry that shows its progress.

interface LoadFailedProps {
  title: string
  description: string
  details: { label: string; value: string }[]
  onRetry: () => Promise<void>
  hint?: string
}

export function LoadFailed({
  title,
  description,
  details,
  onRetry,
  hint,
}: LoadFailedProps) {
  const [retrying, setRetrying] = useState(false)

  return (
    <section className="mt-6 w-full max-w-xl">
      <div className="rounded-[var(--rb-r-4xl)] border border-border bg-[var(--surface-card)] p-1">
        <div
          role="alert"
          className="rounded-[var(--rb-r-2xl)] border border-border bg-canvas p-5 sm:p-6"
        >
          <div className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[var(--warning-pale)] text-[var(--warning-deep)]"
            >
              <TriangleAlertIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-lg font-bold text-heading">
                {title}
              </h1>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {description}
              </p>
            </div>
          </div>

          <dl className="mt-4 space-y-1">
            {details.map((detail) => (
              <div
                key={detail.label}
                className="flex items-center gap-3 rounded-[var(--rb-r-md)] bg-[var(--surface-soft)] px-3 py-2"
              >
                <dt className="w-28 shrink-0 text-xs text-muted-foreground">
                  {detail.label}
                </dt>
                <dd className="min-w-0 flex-1 truncate font-mono text-xs text-heading">
                  {detail.value}
                </dd>
              </div>
            ))}
          </dl>

          <button
            type="button"
            disabled={retrying}
            onClick={async () => {
              setRetrying(true)
              try {
                await onRetry()
              } finally {
                setRetrying(false)
              }
            }}
            className="mt-5 inline-flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-[var(--rb-r-4xl)] bg-primary px-5 text-sm font-bold text-primary-foreground transition-colors duration-150 hover:bg-[var(--primary-pressed)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RotateCwIcon
              aria-hidden="true"
              className={retrying ? "size-4 animate-spin" : "size-4"}
            />
            {retrying ? "Tentando de novo…" : "Tentar de novo"}
          </button>
        </div>
      </div>

      {hint && (
        <p className="mt-3 px-1 text-xs leading-relaxed text-muted-foreground">
          {hint}
        </p>
      )}
    </section>
  )
}
