import {
  CircleAlertIcon,
  CircleCheckIcon,
  InfoIcon,
  TriangleAlertIcon,
} from "lucide-react"

import type { NoticeTone } from "@/lib/notify"

export const noticeIcons: Record<NoticeTone, typeof InfoIcon> = {
  success: CircleCheckIcon,
  error: CircleAlertIcon,
  warning: TriangleAlertIcon,
  info: InfoIcon,
}

// Icon chip colours for each tone, drawn from the design tokens.
export const noticeChip: Record<NoticeTone, string> = {
  success: "bg-[var(--success-pale)] text-[var(--success-deep)]",
  error: "bg-[var(--error-pale)] text-[var(--error-deep)]",
  warning: "bg-[var(--warning-pale)] text-[var(--warning-deep)]",
  info: "bg-[var(--info-pale)] text-[var(--info-deep)]",
}
