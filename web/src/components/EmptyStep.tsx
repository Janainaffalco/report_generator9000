import type { ComponentType, SVGProps } from "react"
import { ArrowRightIcon } from "lucide-react"

import { cn } from "@/lib/utils"

// Adapted from the React Bits Pro block empty-state-1: a ghosted preview of
// what the step will hold, a short explanation, and the paths that fill it.

type Icon = ComponentType<SVGProps<SVGSVGElement>>

export interface EmptyStepPath {
  icon: Icon
  title: string
  body: string
  meta?: string
  onClick: () => void
}

interface EmptyStepProps {
  title: string
  description: string
  paths: EmptyStepPath[]
  primary?: { label: string; icon: Icon; onClick: () => void }
  // A step's own page title is an h1; inside a titled page, pass 2.
  headingLevel?: 1 | 2
}

const frame =
  "rounded-[var(--rb-r-4xl)] border border-border bg-[var(--surface-card)] p-1"
const panel = "rounded-[var(--rb-r-2xl)] border border-border bg-canvas"

const GHOST_ROWS = [
  [72, 40, 28],
  [56, 52, 36],
  [64, 34, 44],
  [48, 46, 30],
]

export function EmptyStep({
  title,
  description,
  paths,
  primary,
  headingLevel = 1,
}: EmptyStepProps) {
  const Heading = headingLevel === 1 ? "h1" : "h2"
  return (
    <section className="mt-6 flex w-full max-w-3xl flex-col">
      <div className="relative">
        <div
          aria-hidden="true"
          className={cn(frame, "pointer-events-none select-none")}
        >
          <div className={cn(panel, "space-y-1 p-1")}>
            {GHOST_ROWS.map((row, rowIndex) => (
              <div
                key={rowIndex}
                className="flex items-center gap-3 rounded-[var(--rb-r-md)] px-3 py-2.5"
                style={{ opacity: 1 - rowIndex * 0.22 }}
              >
                <span className="size-5 shrink-0 rounded-[var(--rb-r-sm)] bg-[var(--hairline-soft)]" />
                {row.map((width, cell) => (
                  <span
                    key={cell}
                    className="h-2 rounded-full bg-[var(--hairline-soft)]"
                    style={{ width }}
                  />
                ))}
                <span className="ml-auto h-2 w-10 rounded-full bg-primary/15" />
              </div>
            ))}
          </div>
        </div>
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-linear-to-b from-transparent to-background"
        />
      </div>

      <div className="mt-6 text-center">
        <Heading className="font-display text-2xl font-bold text-heading">
          {title}
        </Heading>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
          {description}
        </p>
      </div>

      {paths.length > 0 && (
        <div
          className={cn(
            frame,
            "mt-6 grid gap-1",
            paths.length > 1 && "sm:grid-cols-2",
            paths.length > 2 && "md:grid-cols-3"
          )}
        >
          {paths.map(({ icon: PathIcon, title: pathTitle, body, meta, onClick }) => (
            <button
              key={pathTitle}
              type="button"
              onClick={onClick}
              className={cn(
                panel,
                "group cursor-pointer p-4 text-left transition-colors duration-150 hover:border-primary/40 hover:bg-[var(--surface-soft)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)]"
              )}
            >
              <span
                aria-hidden="true"
                className="flex size-8 items-center justify-center rounded-full bg-primary/8 text-primary"
              >
                <PathIcon className="size-4" />
              </span>
              <span className="mt-3 flex items-center gap-1 text-sm font-semibold text-heading">
                {pathTitle}
                <ArrowRightIcon
                  aria-hidden="true"
                  className="size-3 -translate-x-1 opacity-0 transition-[opacity,transform] duration-150 ease-out group-hover:translate-x-0 group-hover:opacity-100"
                />
              </span>
              <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                {body}
              </span>
              {meta && (
                <span className="mt-2 block text-[11px] tracking-[0.06em] text-muted-foreground uppercase">
                  {meta}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {primary && (
        <div className="mt-6 flex justify-center">
          <button
            type="button"
            onClick={primary.onClick}
            className="inline-flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-[var(--rb-r-4xl)] bg-primary px-5 text-sm font-bold text-primary-foreground transition-colors duration-150 hover:bg-[var(--primary-pressed)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)] sm:w-auto"
          >
            <primary.icon aria-hidden="true" className="size-4" />
            {primary.label}
          </button>
        </div>
      )}
    </section>
  )
}
