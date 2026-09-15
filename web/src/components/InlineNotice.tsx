import { useState, type ReactNode } from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { ChevronDownIcon, XIcon } from "lucide-react"

import { noticeChip, noticeIcons } from "@/components/notice-tone"
import type { NoticeTone } from "@/lib/notify"
import { cn } from "@/lib/utils"

// Adapted from the React Bits Pro block notifications-5: one persistent
// banner with a tone, optional expandable details, actions and dismissal.
// Errors are announced as alerts; the other tones as status messages.

interface InlineNoticeProps {
  tone: NoticeTone
  title: string
  children?: ReactNode
  details?: string[]
  action?: { label: string; onClick: () => void }
  onDismiss?: () => void
  className?: string
}

export function InlineNotice({
  tone,
  title,
  children,
  details,
  action,
  onDismiss,
  className,
}: InlineNoticeProps) {
  const reduce = useReducedMotion()
  const [open, setOpen] = useState(false)
  const Icon = noticeIcons[tone]

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "w-full rounded-[var(--rb-r-2xl)] border border-border bg-canvas p-4 text-left",
        className
      )}
    >
      <div className="flex gap-3">
        <span
          aria-hidden="true"
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-full",
            noticeChip[tone]
          )}
        >
          <Icon className="size-4" strokeWidth={2} />
        </span>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-heading">{title}</p>
          {children && (
            <div className="mt-1 max-w-[68ch] text-sm leading-5 text-muted-foreground">
              {children}
            </div>
          )}

          {details && details.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                aria-expanded={open}
                className="mt-2 inline-flex items-center gap-1 rounded-[var(--rb-r-sm)] text-sm font-medium text-foreground transition-colors duration-150 hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)]"
              >
                {open ? "Ocultar detalhes" : "Ver detalhes"}
                <ChevronDownIcon
                  aria-hidden="true"
                  className={cn(
                    "size-3.5 transition-transform duration-150",
                    open && "rotate-180"
                  )}
                />
              </button>
              <AnimatePresence initial={false}>
                {open && (
                  <motion.div
                    initial={reduce ? false : { height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={reduce ? undefined : { height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: "easeOut" }}
                    className="overflow-hidden"
                  >
                    <ul className="mt-2 space-y-px overflow-hidden rounded-[var(--rb-r-md)] bg-border">
                      {details.map((detail) => (
                        <li
                          key={detail}
                          className="bg-[var(--surface-soft)] px-3 py-2 font-mono text-xs text-muted-foreground"
                        >
                          {detail}
                        </li>
                      ))}
                    </ul>
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          )}

          {action && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={action.onClick}
                className="inline-flex h-8 items-center rounded-[var(--rb-r-md)] bg-secondary px-3 text-sm font-semibold text-secondary-foreground transition-colors duration-150 hover:bg-[var(--secondary-pressed)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)]"
              >
                {action.label}
              </button>
            </div>
          )}
        </div>

        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label={`Dispensar: ${title}`}
            className="-mt-1 -mr-1 inline-flex size-7 shrink-0 items-center justify-center rounded-[var(--rb-r-sm)] text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)]"
          >
            <XIcon aria-hidden="true" className="size-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
