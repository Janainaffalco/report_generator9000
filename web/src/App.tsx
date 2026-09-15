import { useCallback, useEffect, useRef, useState } from "react"
import {
  CheckCircle2Icon,
  FileSearchIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  HistoryIcon,
  Layers3Icon,
  ListChecksIcon,
  LoaderCircleIcon,
  MenuIcon,
  ShieldCheckIcon,
  UploadIcon,
} from "lucide-react"

import { BatchGeneration } from "@/components/BatchGeneration"
import { EmptyStep, type EmptyStepPath } from "@/components/EmptyStep"
import { GenerationRun } from "@/components/GenerationRun"
import { LoadFailed } from "@/components/LoadFailed"
import { LoginForm } from "@/components/LoginForm"
import { NotificationsProvider } from "@/components/NotificationsProvider"
import { PastRuns } from "@/components/PastRuns"
import { RetainedSheetPicker } from "@/components/RetainedSheetPicker"
import { UploadPanel } from "@/components/UploadPanel"
import { WorkGroups } from "@/components/WorkGroups"
import {
  WorkflowSidebar,
  type NavIndicator,
  type NavItem,
  type NavSection,
} from "@/components/WorkflowSidebar"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ControlSheetResponse, RetainedSheet } from "@/lib/control-sheet"
import {
  getRetainedControlSheet,
  listRetainedControlSheets,
  uploadControlSheet,
} from "@/lib/control-sheet"
import { useNotify } from "@/lib/notify"
import type {
  BatchResponse,
  PastRun,
  RunOutcome,
  RunResponse,
} from "@/lib/runs"
import {
  getBatch,
  getRun,
  listPastRuns,
  startBatch,
  startRun,
} from "@/lib/runs"
import { getSession, logout } from "@/lib/session"

type View = "upload" | "choose" | "review" | "history"

// The menu is grouped, not numbered: every item can be opened at any time.
const navGroups = ["Gerar", "Arquivo"] as const

const navItems = [
  {
    view: "upload",
    label: "Planilha",
    icon: FileSpreadsheetIcon,
    path: "/",
    group: "Gerar",
  },
  {
    view: "choose",
    label: "Trabalhos",
    icon: ListChecksIcon,
    path: "/escolher",
    group: "Gerar",
  },
  {
    view: "review",
    label: "Em conferência",
    icon: FileSearchIcon,
    path: "/conferir",
    group: "Gerar",
  },
  {
    view: "history",
    label: "Relatórios",
    icon: HistoryIcon,
    path: "/relatorios",
    group: "Arquivo",
  },
] as const satisfies ReadonlyArray<{
  view: View
  label: string
  icon: NavItem["icon"]
  path: string
  group: (typeof navGroups)[number]
}>

const features = [
  {
    title: "Extração automática com consistência de screenshots das páginas",
    description:
      "Capturas organizadas para registrar cada página com consistência.",
    icon: ShieldCheckIcon,
  },
  {
    title: "Extração automática de paleta de cores do site",
    description: "As cores do site são identificadas para compor o relatório.",
    icon: CheckCircle2Icon,
  },
  {
    title: "Documento Word no fim",
    description:
      "O .docx sai pronto para revisão e inclusão de itens que não dependem de LOGIN.",
    icon: FileTextIcon,
  },
]

const CHOOSING_WORK_PATH = "/escolher"
const REVIEW_PATH = "/conferir"

const activeOutcomes: ReadonlySet<RunOutcome> = new Set(["queued", "running"])

function isReviewPath(pathname: string) {
  return /^\/(relatorios|lotes)\/[^/]+$/.test(pathname)
}

// The view a freshly loaded URL opens on, before any data has arrived. Every
// step can be opened on its own; a step without its data shows an empty state.
function initialView(pathname: string): View {
  if (isReviewPath(pathname) || pathname === REVIEW_PATH) {
    return "review"
  }
  if (pathname === "/relatorios") {
    return "history"
  }
  if (pathname === CHOOSING_WORK_PATH) {
    return "choose"
  }
  return "upload"
}

function restoresSheet(pathname: string) {
  return pathname === "/" || pathname === CHOOSING_WORK_PATH
}

function engagementName(run: RunResponse) {
  return `Pasta ${run.engagement.pasta} — ${run.engagement.razao_social}`
}

function formatTime(date: Date) {
  return new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }).format(date)
}

export function App() {
  return (
    <NotificationsProvider>
      <Workspace />
    </NotificationsProvider>
  )
}

function Workspace() {
  const notify = useNotify()
  const [status, setStatus] = useState<"idle" | "loading" | "starting">("idle")
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [controlSheet, setControlSheet] = useState<ControlSheetResponse | null>(
    null
  )
  const [run, setRun] = useState<RunResponse | null>(null)
  const [batch, setBatch] = useState<BatchResponse | null>(null)
  const [pastRuns, setPastRuns] = useState<PastRun[] | null>(null)
  const [pastRunsFailure, setPastRunsFailure] = useState<{
    detail: string
    at: Date
  } | null>(null)
  const [retainedSheets, setRetainedSheets] = useState<RetainedSheet[]>([])
  const [restoringSheet, setRestoringSheet] = useState(
    restoresSheet(window.location.pathname)
  )
  const [loadingReview, setLoadingReview] = useState(
    isReviewPath(window.location.pathname)
  )
  const [auth, setAuth] = useState<"checking" | "signed-out" | "signed-in">(
    "checking"
  )
  // Which step is on screen is kept apart from the data each step holds, so
  // moving between steps never discards a loaded sheet, run, or batch.
  const [view, setView] = useState<View>(() =>
    initialView(window.location.pathname)
  )
  const [navOpen, setNavOpen] = useState(false)
  const navTriggerRef = useRef<HTMLButtonElement>(null)
  const closeNav = useCallback(() => setNavOpen(false), [])

  // Background work reports on the view the consultant is on when it ends,
  // not the one they were on when it started.
  const viewRef = useRef(view)
  useEffect(() => {
    viewRef.current = view
  }, [view])

  const reviewHref = run
    ? `/relatorios/${run.run_id}`
    : batch
      ? `/lotes/${batch.batch_id}`
      : REVIEW_PATH

  const readyCount = controlSheet?.engagements.length ?? 0
  const sheetIssues = controlSheet
    ? controlSheet.stop_conditions.length + controlSheet.unsupported_rows.total
    : 0
  const generating =
    (run !== null && activeOutcomes.has(run.outcome)) ||
    (batch?.runs.some((batchRun) => activeOutcomes.has(batchRun.outcome)) ??
      false)

  function indicatorFor(itemView: View): NavIndicator | undefined {
    if (itemView === "upload" && sheetIssues > 0) {
      return {
        kind: "attention",
        description: `${sheetIssues} ${
          sheetIssues === 1 ? "linha precisa" : "linhas precisam"
        } de atenção`,
      }
    }
    if (itemView === "choose" && readyCount > 0) {
      return {
        kind: "count",
        value: readyCount,
        description: `${readyCount} ${
          readyCount === 1
            ? "trabalho pronto para gerar"
            : "trabalhos prontos para gerar"
        }`,
      }
    }
    if (itemView === "review" && generating) {
      return { kind: "busy", description: "Geração em andamento" }
    }
    return undefined
  }

  const sections: NavSection[] = navGroups.map((group) => ({
    label: group,
    items: navItems
      .filter((item) => item.group === group)
      .map((item) => ({
        id: item.view,
        label: item.label,
        icon: item.icon,
        href: item.view === "review" ? reviewHref : item.path,
        indicator: indicatorFor(item.view),
      })),
  }))

  const announceSheet = useCallback(
    (sheet: ControlSheetResponse, restored: boolean) => {
      const ready = sheet.engagements.length
      notify({
        id: "sheet",
        tone: "success",
        title: restored ? "Planilha recuperada" : "Planilha carregada",
        body: `${sheet.filename} · ${ready} ${
          ready === 1
            ? "trabalho pronto para gerar"
            : "trabalhos prontos para gerar"
        }`,
      })
      const stops = sheet.stop_conditions.length
      const unsupported = sheet.unsupported_rows.total
      if (stops + unsupported > 0) {
        const parts = [
          stops > 0 && `${stops} com Stop Condition`,
          unsupported > 0 && `${unsupported} fora do escopo`,
        ].filter(Boolean)
        notify({
          id: "sheet-attention",
          tone: "warning",
          title: `${stops + unsupported} ${
            stops + unsupported === 1
              ? "linha precisa de atenção"
              : "linhas precisam de atenção"
          }`,
          body: `${parts.join(" · ")}. Confira antes de gerar.`,
        })
      }
    },
    [notify]
  )

  async function handleFile(file: File) {
    setStatus("loading")
    setErrorDetail(null)
    const result = await uploadControlSheet(file)
    setStatus("idle")
    if (result.ok) {
      setControlSheet(result.data)
      setView("choose")
      announceSheet(result.data, false)
      return
    }
    setErrorDetail(result.detail)
  }

  const refreshRun = useCallback(
    async (runId: string) => {
      const result = await getRun(runId)
      if (result.ok) {
        setRun(result.data)
        setErrorDetail(null)
        return
      }
      setErrorDetail(result.detail)
      if (viewRef.current !== "review") {
        notify({
          id: "refresh-run",
          tone: "warning",
          title: "Não foi possível atualizar a geração",
          body: result.detail,
        })
      }
    },
    [notify]
  )

  const refreshBatch = useCallback(
    async (batchId: string) => {
      const result = await getBatch(batchId)
      if (result.ok) {
        setBatch(result.data)
        setErrorDetail(null)
        return
      }
      setErrorDetail(result.detail)
      if (viewRef.current !== "review") {
        notify({
          id: "refresh-batch",
          tone: "warning",
          title: "Não foi possível atualizar o lote",
          body: result.detail,
        })
      }
    },
    [notify]
  )

  const refreshPastRuns = useCallback(async () => {
    const result = await listPastRuns()
    if (result.ok) {
      setPastRuns(result.data)
      setPastRunsFailure(null)
    } else {
      setPastRunsFailure({ detail: result.detail, at: new Date() })
    }
  }, [])

  useEffect(() => {
    void getSession().then((ok) => {
      setAuth(ok ? "signed-in" : "signed-out")
    })
  }, [])

  useEffect(() => {
    if (auth !== "signed-in") {
      return
    }
    const match = window.location.pathname.match(/^\/relatorios\/([^/]+)$/)
    if (match) {
      void getRun(match[1]).then((result) => {
        setLoadingReview(false)
        if (result.ok) {
          setRun(result.data)
          setErrorDetail(null)
        } else {
          setErrorDetail(result.detail)
          setView("upload")
        }
      })
      return
    }
    const batchMatch = window.location.pathname.match(/^\/lotes\/([^/]+)$/)
    if (batchMatch) {
      void getBatch(batchMatch[1]).then((result) => {
        setLoadingReview(false)
        if (result.ok) {
          setBatch(result.data)
          setErrorDetail(null)
        } else {
          setErrorDetail(result.detail)
          setView("upload")
        }
      })
      return
    }
    if (window.location.pathname === "/relatorios") {
      void listPastRuns().then((result) => {
        if (result.ok) {
          setPastRuns(result.data)
          setPastRunsFailure(null)
        } else {
          setPastRunsFailure({ detail: result.detail, at: new Date() })
        }
      })
    }
  }, [auth])

  useEffect(() => {
    if (auth !== "signed-in") {
      return
    }
    if (!restoresSheet(window.location.pathname)) {
      return
    }
    void listRetainedControlSheets().then(async (result) => {
      if (!result.ok) {
        setErrorDetail(result.detail)
        setRestoringSheet(false)
        return
      }
      if (result.data.length === 1) {
        const retained = await getRetainedControlSheet(result.data[0].sheet_id)
        if (retained.ok) {
          setControlSheet(retained.data)
          setView("choose")
          window.history.replaceState({}, "", CHOOSING_WORK_PATH)
          announceSheet(retained.data, true)
        } else {
          setErrorDetail(retained.detail)
        }
      } else if (result.data.length > 1) {
        setRetainedSheets(result.data)
        setView("upload")
      }
      setRestoringSheet(false)
    })
  }, [announceSheet, auth])

  // Browser back/forward: show the step the URL names. A step whose data is
  // missing shows its empty state instead of bouncing to another step.
  useEffect(() => {
    function handlePopState() {
      setErrorDetail(null)
      setView(initialView(window.location.pathname))
    }
    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [])

  useEffect(() => {
    if (!run || run.outcome !== "running") {
      return
    }
    const timer = window.setInterval(() => {
      void refreshRun(run.run_id)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [refreshRun, run])

  useEffect(() => {
    if (
      !batch ||
      !batch.runs.some((batchRun) => activeOutcomes.has(batchRun.outcome))
    ) {
      return
    }
    const timer = window.setInterval(() => {
      void refreshBatch(batch.batch_id)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [batch, refreshBatch])

  function goTo(nextView: View, href: string) {
    setErrorDetail(null)
    setView(nextView)
    window.history.pushState({}, "", href)
  }

  function openRunReview(runId: string) {
    goTo("review", `/relatorios/${runId}`)
  }

  // A run that was generating and has now ended gets one notification, keyed
  // by run so a batch member opened on its own is not announced twice.
  const lastRun = useRef<{ id: string; outcome: RunOutcome } | null>(null)
  useEffect(() => {
    const previous = lastRun.current
    lastRun.current = run ? { id: run.run_id, outcome: run.outcome } : null
    if (
      !run ||
      !previous ||
      previous.id !== run.run_id ||
      !activeOutcomes.has(previous.outcome) ||
      activeOutcomes.has(run.outcome)
    ) {
      return
    }
    const action =
      viewRef.current === "review"
        ? undefined
        : { label: "Conferir", onClick: () => openRunReview(run.run_id) }
    notify({ ...runEndedNotice(run), id: `run-${run.run_id}`, action })
    // openRunReview only touches state setters and history.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notify, run])

  const lastBatch = useRef<{
    id: string
    outcomes: Map<string, RunOutcome>
  } | null>(null)
  useEffect(() => {
    const previous = lastBatch.current
    lastBatch.current = batch
      ? {
          id: batch.batch_id,
          outcomes: new Map(
            batch.runs.map((item) => [item.run_id, item.outcome])
          ),
        }
      : null
    if (!batch || !previous || previous.id !== batch.batch_id) {
      return
    }
    for (const item of batch.runs) {
      const before = previous.outcomes.get(item.run_id)
      if (
        before &&
        activeOutcomes.has(before) &&
        !activeOutcomes.has(item.outcome) &&
        item.outcome !== "finished"
      ) {
        notify({ ...runEndedNotice(item), id: `run-${item.run_id}` })
      }
    }
    const wasActive = [...previous.outcomes.values()].some((outcome) =>
      activeOutcomes.has(outcome)
    )
    const isActive = batch.runs.some((item) => activeOutcomes.has(item.outcome))
    if (wasActive && !isActive) {
      const finished = batch.runs.filter(
        (item) => item.outcome === "finished"
      ).length
      const total = batch.runs.length
      notify({
        id: `batch-${batch.batch_id}`,
        tone: finished === total ? "success" : "warning",
        title:
          finished === total
            ? "Todos os relatórios do lote foram gerados"
            : "O lote terminou com problemas",
        body: `${finished} de ${total} ${
          total === 1 ? "relatório gerado" : "relatórios gerados"
        }`,
        action:
          viewRef.current === "review"
            ? undefined
            : {
                label: "Ver lote",
                onClick: () => goTo("review", `/lotes/${batch.batch_id}`),
              },
      })
    }
  }, [batch, notify])

  function forgetExpiredSheet() {
    setControlSheet(null)
    setRetainedSheets([])
    setView("upload")
    window.history.replaceState({}, "", "/enviar")
  }

  async function handleGenerate(rowNumbers: number[]) {
    if (!controlSheet) {
      return
    }
    setStatus("starting")
    setErrorDetail(null)
    if (rowNumbers.length > 1) {
      const result = await startBatch(controlSheet.sheet_id, rowNumbers)
      setStatus("idle")
      if (!result.ok) {
        setErrorDetail(result.detail)
        if (result.status === 404) {
          forgetExpiredSheet()
        }
        return
      }
      window.history.pushState({}, "", `/lotes/${result.data.batch_id}`)
      setRun(null)
      setBatch(result.data)
      setView("review")
      notify({
        tone: "info",
        title: "Lote iniciado",
        body: `${result.data.runs.length} relatórios na fila de geração`,
      })
      return
    }
    const result = await startRun(controlSheet.sheet_id, rowNumbers[0])
    setStatus("idle")
    if (!result.ok) {
      setErrorDetail(result.detail)
      if (result.status === 404) {
        forgetExpiredSheet()
      }
      return
    }
    window.history.pushState({}, "", `/relatorios/${result.data.run_id}`)
    setRun(result.data)
    setView("review")
    notify({
      tone: "info",
      title: "Geração iniciada",
      body: engagementName(result.data),
    })
  }

  async function handleRetainedSheet(sheetId: string) {
    setStatus("loading")
    setErrorDetail(null)
    const retained = await getRetainedControlSheet(sheetId)
    setStatus("idle")
    setRetainedSheets([])
    if (retained.ok) {
      setControlSheet(retained.data)
      setView("choose")
      window.history.replaceState({}, "", CHOOSING_WORK_PATH)
      announceSheet(retained.data, true)
      return
    }
    setErrorDetail(retained.detail)
    window.history.replaceState({}, "", "/enviar")
  }

  async function handleBackToRows() {
    const sheetId = run?.sheet_id ?? batch?.sheet_id
    if (!controlSheet && sheetId) {
      const result = await getRetainedControlSheet(sheetId)
      if (!result.ok) {
        setErrorDetail(result.detail)
        setRun(null)
        setControlSheet(null)
        setRetainedSheets([])
        setView("upload")
        window.history.pushState({}, "", "/enviar")
        return
      }
      setControlSheet(result.data)
    }
    setErrorDetail(null)
    setRun(null)
    setBatch(null)
    setView("choose")
    window.history.pushState({}, "", CHOOSING_WORK_PATH)
  }

  function handleOpenBatchRun(batchRun: RunResponse) {
    setRun(batchRun)
    window.history.pushState({}, "", `/relatorios/${batchRun.run_id}`)
  }

  function handleBackToBatch() {
    if (!batch) {
      return
    }
    setRun(null)
    setView("review")
    window.history.pushState({}, "", `/lotes/${batch.batch_id}`)
  }

  async function handleOpenHistory() {
    goTo("history", "/relatorios")
    setStatus("loading")
    await refreshPastRuns()
    setStatus("idle")
  }

  function handleNavigate(step: NavItem) {
    const target = navItems.find((item) => item.view === step.id)
    if (!target || target.view === view) {
      return
    }
    if (target.view === "history") {
      void handleOpenHistory()
      return
    }
    goTo(target.view, step.href)
  }

  async function handleLogout() {
    await logout()
    setAuth("signed-out")
    setControlSheet(null)
    setRun(null)
    setBatch(null)
    setPastRuns(null)
    setPastRunsFailure(null)
    setRetainedSheets([])
    setErrorDetail(null)
    setRestoringSheet(false)
    setLoadingReview(false)
    setNavOpen(false)
    setView("upload")
  }

  async function handleOpenPastRun(pastRun: PastRun) {
    setStatus("loading")
    setErrorDetail(null)
    const result = await getRun(pastRun.run_id)
    setStatus("idle")
    if (!result.ok) {
      setErrorDetail(result.detail)
      return
    }
    setRun(result.data)
    setView("review")
    window.history.pushState({}, "", pastRun.review_url)
  }

  const runBelongsToBatch =
    run !== null &&
    batch !== null &&
    batch.runs.some((batchRun) => batchRun.run_id === run.run_id)

  const uploadPath: EmptyStepPath = {
    icon: UploadIcon,
    title: "Enviar a planilha",
    body: "Arraste o arquivo .xlsx de controle ou escolha no computador.",
    meta: "Planilha",
    onClick: () => goTo("upload", "/"),
  }
  const choosePath: EmptyStepPath = {
    icon: ListChecksIcon,
    title: "Escolher o trabalho",
    body: `Selecione um ou mais trabalhos de ${controlSheet?.filename ?? "a planilha"} para gerar.`,
    meta: "Trabalhos",
    onClick: () => goTo("choose", CHOOSING_WORK_PATH),
  }
  const historyPath: EmptyStepPath = {
    icon: HistoryIcon,
    title: "Ver relatórios anteriores",
    body: "Confira ou baixe o que foi gerado nos últimos sete dias.",
    meta: "Relatórios",
    onClick: () => void handleOpenHistory(),
  }
  const startPath = controlSheet ? choosePath : uploadPath

  return (
    <div className="flex min-h-screen min-w-0 bg-background">
      {auth === "signed-in" && (
        <WorkflowSidebar
          sections={sections}
          activeId={view}
          onNavigate={handleNavigate}
          onLogout={() => void handleLogout()}
          mobileOpen={navOpen}
          onMobileClose={closeNav}
          mobileTriggerRef={navTriggerRef}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-border bg-canvas">
          <div className="mx-auto flex w-full max-w-(--container-max) min-w-0 flex-wrap items-center justify-between gap-3 px-6 py-4 lg:px-10">
            <div className="flex min-w-0 items-center gap-3">
              {auth === "signed-in" && (
                <button
                  ref={navTriggerRef}
                  type="button"
                  aria-label="Abrir navegação"
                  aria-expanded={navOpen}
                  onClick={() => setNavOpen(true)}
                  className="inline-flex size-9 shrink-0 items-center justify-center rounded-sm bg-muted text-foreground transition-colors hover:bg-secondary lg:hidden"
                >
                  <MenuIcon aria-hidden="true" className="size-4" />
                </button>
              )}
              <span className="min-w-0 truncate font-display text-lg font-bold text-primary sm:text-xl">
                Gerador de Relatórios SEBRAETEC
              </span>
            </div>
            {auth === "signed-in" && batch && (
              <Button
                className="batch-jump"
                aria-current={view === "review" && !run ? "page" : undefined}
                onClick={handleBackToBatch}
              >
                {batch.runs.some((batchRun) =>
                  activeOutcomes.has(batchRun.outcome)
                ) ? (
                  <LoaderCircleIcon
                    aria-hidden="true"
                    className="batch-jump-icon animate-spin"
                  />
                ) : (
                  <Layers3Icon aria-hidden="true" className="batch-jump-icon" />
                )}
                Ir para o lote atual
                <span className="batch-jump-count" aria-hidden="true">
                  {batch.runs.length}
                </span>
              </Button>
            )}
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-(--container-max) min-w-0 flex-1 flex-col items-center px-6 py-14 lg:px-10">
          {auth === "checking" ? (
            <p role="status" className="mt-10 text-sm text-muted-foreground">
              Verificando o acesso…
            </p>
          ) : auth === "signed-out" ? (
            <LoginForm onSignedIn={() => setAuth("signed-in")} />
          ) : (
            <>
              {/* Steps that hold their own state (the work table's selection
                  and filters, the review's page) stay mounted and are only
                  hidden, so they survive a step switch. The stateless steps
                  simply render when active. */}
              {view === "upload" && (
                <div className="flex w-full min-w-0 flex-col items-center">
                  {retainedSheets.length > 1 ? (
                    <RetainedSheetPicker
                      sheets={retainedSheets}
                      onSelect={(sheetId) => void handleRetainedSheet(sheetId)}
                    />
                  ) : restoringSheet ? (
                    <p
                      role="status"
                      className="mt-10 text-sm text-muted-foreground"
                    >
                      Procurando a planilha mais recente no servidor…
                    </p>
                  ) : (
                    <>
                      <UploadPanel
                        status={status === "loading" ? "loading" : "idle"}
                        errorDetail={errorDetail}
                        onFile={handleFile}
                      />

                      <section
                        aria-label="Como funciona"
                        className="mt-10 grid w-full max-w-5xl grid-cols-1 gap-5 md:grid-cols-3"
                      >
                        {features.map(({ title, description, icon: Icon }) => (
                          <Card key={title}>
                            <CardHeader>
                              <Icon aria-hidden="true" />
                              <CardTitle>{title}</CardTitle>
                            </CardHeader>
                            <CardContent>
                              <p className="leading-5 text-muted-foreground">
                                {description}
                              </p>
                            </CardContent>
                          </Card>
                        ))}
                      </section>
                    </>
                  )}
                </div>
              )}

              <div
                hidden={view !== "choose"}
                className="flex w-full min-w-0 flex-col items-center"
              >
                {controlSheet ? (
                  <WorkGroups
                    key={controlSheet.sheet_id}
                    data={controlSheet}
                    status={status}
                    errorDetail={view === "choose" ? errorDetail : null}
                    onReplaceFile={handleFile}
                    onGenerate={handleGenerate}
                  />
                ) : (
                  view === "choose" &&
                  (restoringSheet ? (
                    <p
                      role="status"
                      className="mt-10 text-sm text-muted-foreground"
                    >
                      Procurando a planilha mais recente no servidor…
                    </p>
                  ) : (
                    <EmptyStep
                      title="Nenhuma planilha carregada"
                      description="Envie a planilha de controle para ver os trabalhos prontos para gerar. Planilhas enviadas ficam guardadas no servidor por sete dias."
                      paths={[uploadPath, historyPath]}
                    />
                  ))
                )}
              </div>

              <div
                hidden={view !== "review"}
                className="flex w-full min-w-0 flex-col items-center"
              >
                {run ? (
                  <GenerationRun
                    run={run}
                    errorDetail={view === "review" ? errorDetail : null}
                    onRefresh={() => void refreshRun(run.run_id)}
                    onBackToRows={() => void handleBackToRows()}
                    onBackToBatch={
                      runBelongsToBatch ? handleBackToBatch : undefined
                    }
                    onRegenerated={(rerun) => {
                      setRun(rerun)
                      window.history.pushState(
                        {},
                        "",
                        `/relatorios/${rerun.run_id}`
                      )
                    }}
                  />
                ) : batch ? (
                  <BatchGeneration
                    batch={batch}
                    errorDetail={view === "review" ? errorDetail : null}
                    onRefresh={() => void refreshBatch(batch.batch_id)}
                    onOpenRun={handleOpenBatchRun}
                    onBackToRows={() => void handleBackToRows()}
                  />
                ) : (
                  view === "review" &&
                  (loadingReview ? (
                    <p
                      role="status"
                      className="mt-10 text-sm text-muted-foreground"
                    >
                      Carregando o relatório…
                    </p>
                  ) : (
                    <EmptyStep
                      title="Nenhum relatório em conferência"
                      description="Escolha um ou mais trabalhos e gere os relatórios. Eles aparecem aqui enquanto são gerados e quando ficam prontos para conferência."
                      paths={[startPath, historyPath]}
                    />
                  ))
                )}
              </div>

              {view === "history" && (
                <div className="flex w-full min-w-0 flex-col items-center">
                  {pastRunsFailure && pastRuns === null ? (
                    <LoadFailed
                      title="Não foi possível carregar os relatórios anteriores"
                      description={pastRunsFailure.detail}
                      details={[
                        { label: "Consulta", value: "GET /api/runs" },
                        {
                          label: "Última tentativa",
                          value: formatTime(pastRunsFailure.at),
                        },
                      ]}
                      onRetry={refreshPastRuns}
                      hint="Se continuar falhando, fale com o suporte pelo WhatsApp informado no rodapé."
                    />
                  ) : pastRuns !== null ? (
                    <PastRuns
                      runs={pastRuns}
                      errorDetail={
                        errorDetail ?? pastRunsFailure?.detail ?? null
                      }
                      emptyPaths={[startPath]}
                      onOpen={(pastRun) => void handleOpenPastRun(pastRun)}
                    />
                  ) : (
                    <p
                      role="status"
                      className="mt-10 text-sm text-muted-foreground"
                    >
                      Carregando os relatórios anteriores…
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </main>

        <footer className="border-t border-border bg-canvas">
          <div className="mx-auto flex w-full max-w-(--container-max) flex-wrap items-center justify-between gap-x-8 gap-y-3 px-6 py-5 text-xs text-muted-foreground lg:px-10">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="beta-tag">Beta</span>
              <a className="footer-link" href="https://wa.me/5511911926036">
                Suporte via WhatsApp: (11) 91192-6036
              </a>
              <a
                className="footer-link"
                href="https://github.com/placeholder/report_generator9000"
                target="_blank"
                rel="noreferrer"
              >
                GitHub (em breve)
              </a>
            </div>
            <p className="max-w-xl sm:text-right">
              As planilhas enviadas e os arquivos de cada relatório são mantidos
              no servidor por sete dias. Nenhum dado do cliente é enviado a uma
              conta de terceiros.
            </p>
          </div>
        </footer>
      </div>
    </div>
  )
}

function runEndedNotice(run: RunResponse) {
  const name = engagementName(run)
  switch (run.outcome) {
    case "finished":
      return run.status === "draft"
        ? {
            tone: "warning" as const,
            title: "Relatório gerado com Pendências",
            body: name,
          }
        : { tone: "success" as const, title: "Relatório gerado", body: name }
    case "stopped":
      return {
        tone: "warning" as const,
        title: "Geração interrompida",
        body: run.reason ?? name,
      }
    case "rejected":
      return {
        tone: "error" as const,
        title: "Documento recusado pelas conferências",
        body: name,
      }
    default:
      return {
        tone: "error" as const,
        title: "A geração falhou",
        body: run.reason ?? name,
      }
  }
}

export default App
