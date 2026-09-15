import {
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentType,
  type RefObject,
} from "react"
import {
  LoaderCircleIcon,
  LogOutIcon,
  PanelLeftIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"

// Adapted from the React Bits Pro block app-sidebar-1: same collapsible
// desktop rail, grouped sections with trailing badges, and focus-trapped
// mobile drawer, restyled to the design tokens.

export type NavIndicator =
  | { kind: "count"; value: number; description: string }
  | { kind: "busy"; description: string }
  | { kind: "attention"; description: string }

export interface NavItem {
  id: string
  label: string
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" }>
  href: string
  indicator?: NavIndicator
}

export interface NavSection {
  label: string
  items: NavItem[]
}

interface WorkflowSidebarProps {
  sections: NavSection[]
  activeId: string
  onNavigate: (item: NavItem) => void
  onLogout: () => void
  mobileOpen: boolean
  onMobileClose: () => void
  mobileTriggerRef: RefObject<HTMLButtonElement | null>
}

function IndicatorMark({
  indicator,
  collapsed,
}: {
  indicator: NavIndicator
  collapsed: boolean
}) {
  if (collapsed) {
    // The rail has no room for a badge, so a dot on the icon keeps the status
    // visible; the full description still reaches assistive tech.
    return (
      <span
        aria-hidden="true"
        className={cn(
          "absolute -top-0.5 -right-0.5 size-2 rounded-full ring-2 ring-canvas",
          indicator.kind === "attention"
            ? "bg-[var(--warning-deep)]"
            : indicator.kind === "busy"
              ? "animate-pulse bg-primary motion-reduce:animate-none"
              : "bg-muted-foreground"
        )}
      />
    )
  }
  if (indicator.kind === "busy") {
    return (
      <LoaderCircleIcon
        aria-hidden="true"
        className="size-3.5 shrink-0 animate-spin text-primary motion-reduce:animate-none"
      />
    )
  }
  if (indicator.kind === "attention") {
    return (
      <TriangleAlertIcon
        aria-hidden="true"
        className="size-3.5 shrink-0 text-[var(--warning-deep)]"
      />
    )
  }
  return (
    <span
      aria-hidden="true"
      className="text-xs text-muted-foreground tabular-nums"
    >
      {indicator.value}
    </span>
  )
}

function SidebarLink({
  item,
  current,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  current: boolean
  collapsed: boolean
  onNavigate: (item: NavItem) => void
}) {
  const descriptionId = useId()
  const Icon = item.icon
  const { indicator } = item
  return (
    <>
      <a
        href={item.href}
        aria-current={current ? "page" : undefined}
        aria-describedby={indicator ? descriptionId : undefined}
        title={
          collapsed
            ? indicator
              ? `${item.label} · ${indicator.description}`
              : item.label
            : undefined
        }
        onClick={(event) => {
          event.preventDefault()
          onNavigate(item)
        }}
        className={cn(
          "flex h-10 items-center gap-2.5 rounded-sm px-2.5 text-sm transition-colors",
          current
            ? "bg-primary/8 font-semibold text-primary"
            : "text-foreground hover:bg-muted",
          collapsed && "justify-center px-0"
        )}
      >
        <span className="relative inline-flex shrink-0">
          <Icon
            aria-hidden="true"
            className={cn(
              "size-4",
              current ? "text-primary" : "text-muted-foreground"
            )}
          />
          {indicator && collapsed && (
            <IndicatorMark indicator={indicator} collapsed />
          )}
        </span>
        <span className={cn("min-w-0 flex-1 truncate", collapsed && "sr-only")}>
          {item.label}
        </span>
        {indicator && !collapsed && (
          <IndicatorMark indicator={indicator} collapsed={false} />
        )}
      </a>
      {/* Kept outside the link so the status describes it instead of being
        read as part of its name. */}
      {indicator && (
        <span id={descriptionId} hidden>
          {indicator.description}
        </span>
      )}
    </>
  )
}

function SidebarBody({
  sections,
  activeId,
  collapsed,
  onNavigate,
  onLogout,
  onToggleCollapse,
  onClose,
}: {
  sections: NavSection[]
  activeId: string
  collapsed: boolean
  onNavigate: (item: NavItem) => void
  onLogout: () => void
  onToggleCollapse?: () => void
  onClose?: () => void
}) {
  return (
    <>
      <div className="flex h-16 shrink-0 items-center gap-2.5 px-3">
        <span
          aria-hidden="true"
          className="sidebar-mark flex size-9 shrink-0 items-center justify-center rounded-sm font-display text-sm font-bold text-primary-foreground"
        >
          GR
        </span>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate font-display text-sm font-bold text-heading">
              Relatórios
            </p>
            <p className="truncate text-xs text-muted-foreground">SEBRAETEC</p>
          </div>
        )}
        {onClose && (
          <button
            type="button"
            aria-label="Fechar navegação"
            onClick={onClose}
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <XIcon aria-hidden="true" className="size-4" />
          </button>
        )}
      </div>

      <nav
        aria-label="Navegação principal"
        className="min-h-0 flex-1 overflow-y-auto px-2 pt-2 pb-3"
      >
        <div className="space-y-4">
          {sections.map((section) => (
            <div key={section.label}>
              {collapsed ? (
                <span className="sr-only">{section.label}</span>
              ) : (
                <p className="mb-1 px-3 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                  {section.label}
                </p>
              )}
              <ul className="flex flex-col gap-0.5">
                {section.items.map((item) => (
                  <li key={item.id}>
                    <SidebarLink
                      item={item}
                      current={item.id === activeId}
                      collapsed={collapsed}
                      onNavigate={onNavigate}
                    />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </nav>

      <div className="flex shrink-0 flex-col gap-1 border-t border-border p-2">
        {onToggleCollapse && (
          <button
            type="button"
            aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
            title={collapsed ? "Expandir menu" : undefined}
            onClick={onToggleCollapse}
            className={cn(
              "flex h-9 w-full items-center gap-2.5 rounded-sm px-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              collapsed && "justify-center px-0"
            )}
          >
            <PanelLeftIcon aria-hidden="true" className="size-4 shrink-0" />
            {!collapsed && <span className="truncate">Recolher menu</span>}
          </button>
        )}
        <button
          type="button"
          title={collapsed ? "Sair" : undefined}
          onClick={onLogout}
          className={cn(
            "flex h-9 w-full items-center gap-2.5 rounded-sm px-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            collapsed && "justify-center px-0"
          )}
        >
          <LogOutIcon aria-hidden="true" className="size-4 shrink-0" />
          <span className={cn("truncate", collapsed && "sr-only")}>Sair</span>
        </button>
      </div>
    </>
  )
}

export function WorkflowSidebar({
  sections,
  activeId,
  onNavigate,
  onLogout,
  mobileOpen,
  onMobileClose,
  mobileTriggerRef,
}: WorkflowSidebarProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [drawerShown, setDrawerShown] = useState(false)
  const drawerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!mobileOpen) {
      return
    }
    const drawer = drawerRef.current
    const trigger = mobileTriggerRef.current
    const frame = requestAnimationFrame(() => setDrawerShown(true))
    const getFocusable = () =>
      Array.from(
        drawer?.querySelectorAll<HTMLElement>(
          'button, [href], [tabindex]:not([tabindex="-1"])'
        ) ?? []
      ).filter((element) => !element.hasAttribute("disabled"))
    getFocusable()[0]?.focus({ preventScroll: true })

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onMobileClose()
        return
      }
      if (event.key !== "Tab") {
        return
      }
      const focusable = getFocusable()
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) {
        return
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus({ preventScroll: true })
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus({ preventScroll: true })
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => {
      cancelAnimationFrame(frame)
      setDrawerShown(false)
      document.removeEventListener("keydown", onKeyDown)
      trigger?.focus({ preventScroll: true })
    }
  }, [mobileOpen, mobileTriggerRef, onMobileClose])

  return (
    <>
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-canvas transition-[width] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] lg:flex",
          collapsed ? "w-[4.5rem]" : "w-64"
        )}
      >
        <SidebarBody
          sections={sections}
          activeId={activeId}
          collapsed={collapsed}
          onNavigate={onNavigate}
          onLogout={onLogout}
          onToggleCollapse={() => setCollapsed((value) => !value)}
        />
      </aside>

      {mobileOpen && (
        <div className="lg:hidden">
          <button
            type="button"
            aria-label="Fechar navegação"
            tabIndex={-1}
            onClick={onMobileClose}
            className={cn(
              "fixed inset-0 z-30 bg-black/40 backdrop-blur-[2px] transition-opacity duration-200 ease-out",
              drawerShown ? "opacity-100" : "opacity-0"
            )}
          />
          <aside
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navegação"
            className={cn(
              "fixed inset-y-0 left-0 z-40 flex w-72 max-w-[85%] flex-col rounded-r-md bg-canvas shadow-(--shadow-modal) transition-transform duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]",
              drawerShown ? "translate-x-0" : "-translate-x-full"
            )}
          >
            <SidebarBody
              sections={sections}
              activeId={activeId}
              collapsed={false}
              onNavigate={(item) => {
                onMobileClose()
                onNavigate(item)
              }}
              onLogout={onLogout}
              onClose={onMobileClose}
            />
          </aside>
        </div>
      )}
    </>
  )
}
