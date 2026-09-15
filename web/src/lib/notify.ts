import { createContext, useContext } from "react"

export type NoticeTone = "success" | "error" | "warning" | "info"

export interface Notification {
  // Reusing an id replaces that toast instead of stacking a duplicate, so a
  // repeating condition (a poll that keeps failing) shows up once.
  id?: string
  tone: NoticeTone
  title: string
  body?: string
  action?: { label: string; onClick: () => void }
}

export const NotifyContext = createContext<(notification: Notification) => void>(
  () => {}
)

export function useNotify() {
  return useContext(NotifyContext)
}
