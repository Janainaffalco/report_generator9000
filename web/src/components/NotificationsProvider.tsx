import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { XIcon } from "lucide-react"

import { noticeChip, noticeIcons } from "@/components/notice-tone"
import { NotifyContext, type Notification } from "@/lib/notify"
import { cn } from "@/lib/utils"

// Adapted from the React Bits Pro block notifications-2: a toast stack that
// collapses when idle, fans out on hover or focus, and pauses its timers
// while expanded. Restyled to the design tokens.

type Toast = Notification & { id: string }

const ROW = 76
const MAX_VISIBLE = 3
const DURATION = { success: 6000, info: 6000, warning: 10000, error: 10000 }

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion()
  const seq = useRef(0)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [expanded, setExpanded] = useState(false)

  const dismiss = useCallback(
    (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)),
    []
  )

  const notify = useCallback((notification: Notification) => {
    seq.current += 1
    const id = notification.id ?? `toast-${seq.current}`
    setToasts((prev) => [
      { ...notification, id },
      ...prev.filter((t) => t.id !== id),
    ])
  }, [])

  const stack = toasts.slice(0, MAX_VISIBLE + 2)

  return (
    <NotifyContext.Provider value={notify}>
      {children}
      <div
        role="region"
        aria-live="polite"
        aria-label="Notificações"
        onMouseEnter={() => setExpanded(true)}
        onMouseLeave={() => setExpanded(false)}
        onFocus={() => setExpanded(true)}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) {
            setExpanded(false)
          }
        }}
        style={{ height: ROW }}
        className="pointer-events-none fixed right-4 bottom-4 left-4 z-50 sm:left-auto sm:w-[380px]"
      >
        <AnimatePresence initial={false}>
          {stack.map((toast, index) => {
            const depth = Math.min(index, MAX_VISIBLE)
            return (
              <motion.div
                key={toast.id}
                initial={reduce ? false : { opacity: 0, y: 24, scale: 0.96 }}
                animate={{
                  opacity: index >= MAX_VISIBLE ? 0 : 1,
                  y: expanded ? -index * (ROW + 8) : -depth * 10,
                  scale: expanded ? 1 : 1 - depth * 0.04,
                }}
                exit={
                  reduce
                    ? undefined
                    : {
                        opacity: 0,
                        y: 16,
                        scale: 0.96,
                        transition: { duration: 0.16 },
                      }
                }
                transition={
                  reduce
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 380, damping: 34 }
                }
                style={{ zIndex: 50 - index, height: ROW }}
                className={cn(
                  "absolute inset-x-0 bottom-0 origin-bottom",
                  index < MAX_VISIBLE && "pointer-events-auto"
                )}
              >
                <ToastRow
                  toast={toast}
                  paused={expanded}
                  onDismiss={dismiss}
                />
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </NotifyContext.Provider>
  )
}

function ToastRow({
  toast,
  paused,
  onDismiss,
}: {
  toast: Toast
  paused: boolean
  onDismiss: (id: string) => void
}) {
  const reduce = useReducedMotion()
  const { id, tone } = toast
  const Icon = noticeIcons[tone]
  const duration = DURATION[tone]

  useEffect(() => {
    if (paused) {
      return
    }
    const timer = window.setTimeout(() => onDismiss(id), duration)
    return () => window.clearTimeout(timer)
  }, [id, paused, duration, onDismiss])

  return (
    <div className="relative flex h-full items-start gap-3 overflow-hidden rounded-[var(--rb-r-2xl)] border border-border bg-canvas p-3 shadow-[0_12px_32px_-14px_rgba(0,0,0,0.28)]">
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
        <p className="truncate text-sm font-semibold text-heading">
          {toast.title}
        </p>
        {toast.body && (
          <p className="truncate text-[13px] leading-5 text-muted-foreground">
            {toast.body}
          </p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {toast.action && (
          <button
            type="button"
            onClick={() => {
              toast.action?.onClick()
              onDismiss(id)
            }}
            className="inline-flex h-7 items-center rounded-[var(--rb-r-md)] bg-primary px-2.5 text-xs font-semibold text-primary-foreground transition-colors duration-150 hover:bg-[var(--primary-pressed)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)]"
          >
            {toast.action.label}
          </button>
        )}
        <button
          type="button"
          onClick={() => onDismiss(id)}
          aria-label={`Dispensar: ${toast.title}`}
          className="inline-flex size-7 items-center justify-center rounded-[var(--rb-r-md)] text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-outer)]"
        >
          <XIcon aria-hidden="true" className="size-3.5" />
        </button>
      </div>

      {!reduce && (
        <motion.span
          key={paused ? "paused" : "running"}
          aria-hidden="true"
          initial={{ scaleX: 1 }}
          animate={{ scaleX: paused ? 1 : 0 }}
          transition={{ duration: paused ? 0 : duration / 1000, ease: "linear" }}
          className="absolute inset-x-0 bottom-0 h-0.5 origin-left bg-primary/40"
        />
      )}
    </div>
  )
}
