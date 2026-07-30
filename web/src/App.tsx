import { useCallback, useEffect, useState, type CSSProperties } from "react"
import { CheckCircle2Icon, FileTextIcon, ShieldCheckIcon } from "lucide-react"

import { GenerationRun } from "@/components/GenerationRun"
import { RetainedSheetPicker } from "@/components/RetainedSheetPicker"
import { UploadPanel } from "@/components/UploadPanel"
import { WorkGroups } from "@/components/WorkGroups"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import type { ControlSheetResponse, RetainedSheet } from "@/lib/control-sheet"
import {
  getRetainedControlSheet,
  listRetainedControlSheets,
  uploadControlSheet,
} from "@/lib/control-sheet"
import type { RunResponse } from "@/lib/runs"
import { getRun, startRun } from "@/lib/runs"
import { cn } from "@/lib/utils"

const stages = [
  { number: 1, label: "Enviar planilha", path: "/enviar" },
  { number: 2, label: "Escolher o trabalho", path: "/escolher" },
  { number: 3, label: "Conferir o relatório", path: "/conferir" },
  { number: 4, label: "Baixar", path: "/baixar" },
]

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

function currentStage(pathname: string) {
  const stage = stages.find((item) => pathname.startsWith(item.path))
  return stage?.number ?? 1
}

export function App() {
  const [status, setStatus] = useState<"idle" | "loading" | "starting">("idle")
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [controlSheet, setControlSheet] = useState<ControlSheetResponse | null>(
    null
  )
  const [run, setRun] = useState<RunResponse | null>(null)
  const [retainedSheets, setRetainedSheets] = useState<RetainedSheet[]>([])
  const [restoringSheet, setRestoringSheet] = useState(
    window.location.pathname === "/"
  )

  const activeStage = currentStage(
    run
      ? "/conferir"
      : controlSheet
        ? CHOOSING_WORK_PATH
        : window.location.pathname
  )

  async function handleFile(file: File) {
    setStatus("loading")
    setErrorDetail(null)
    const result = await uploadControlSheet(file)
    setStatus("idle")
    if (result.ok) {
      setControlSheet(result.data)
      return
    }
    setErrorDetail(result.detail)
  }

  const refreshRun = useCallback(async (runId: string) => {
    const result = await getRun(runId)
    if (result.ok) {
      setRun(result.data)
      setErrorDetail(null)
      return
    }
    setErrorDetail(result.detail)
  }, [])

  useEffect(() => {
    const match = window.location.pathname.match(/^\/relatorios\/([^/]+)$/)
    if (match) {
      void getRun(match[1]).then((result) => {
        if (result.ok) {
          setRun(result.data)
          setErrorDetail(null)
        } else {
          setErrorDetail(result.detail)
        }
      })
    }
  }, [refreshRun])

  useEffect(() => {
    if (window.location.pathname !== "/") {
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
          window.history.replaceState({}, "", CHOOSING_WORK_PATH)
        } else {
          setErrorDetail(retained.detail)
        }
      } else if (result.data.length > 1) {
        setRetainedSheets(result.data)
      }
      setRestoringSheet(false)
    })
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

  async function handleGenerate(rowNumber: number) {
    if (!controlSheet) {
      return
    }
    setStatus("starting")
    setErrorDetail(null)
    const result = await startRun(controlSheet.sheet_id, rowNumber)
    setStatus("idle")
    if (!result.ok) {
      setErrorDetail(result.detail)
      if (result.status === 404) {
        setControlSheet(null)
        setRetainedSheets([])
        window.history.replaceState({}, "", "/enviar")
      }
      return
    }
    window.history.pushState({}, "", `/relatorios/${result.data.run_id}`)
    setRun(result.data)
  }

  async function handleRetainedSheet(sheetId: string) {
    setStatus("loading")
    setErrorDetail(null)
    const retained = await getRetainedControlSheet(sheetId)
    setStatus("idle")
    setRetainedSheets([])
    if (retained.ok) {
      setControlSheet(retained.data)
      window.history.replaceState({}, "", CHOOSING_WORK_PATH)
      return
    }
    setErrorDetail(retained.detail)
    window.history.replaceState({}, "", "/enviar")
  }

  async function handleBackToRows() {
    if (!controlSheet && run) {
      const result = await getRetainedControlSheet(run.sheet_id)
      if (!result.ok) {
        setErrorDetail(result.detail)
        setRun(null)
        setControlSheet(null)
        setRetainedSheets([])
        window.history.pushState({}, "", "/enviar")
        return
      }
      setControlSheet(result.data)
    }
    setErrorDetail(null)
    setRun(null)
    window.history.pushState({}, "", CHOOSING_WORK_PATH)
  }

  return (
    <div className="flex min-h-screen min-w-0 flex-col bg-background">
      <header className="border-b border-border bg-canvas">
        <div className="mx-auto flex w-full max-w-(--container-max) min-w-0 flex-col items-stretch gap-3 px-8 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
          <span className="font-display text-lg font-bold text-primary sm:min-w-0 sm:truncate sm:text-xl">
            Gerador de Relatórios SEBRAETEC
          </span>
          <div className="flex shrink-0 items-center justify-between gap-4 sm:justify-end">
            <a
              className={buttonVariants({ variant: "secondary" })}
              href="/relatorios"
            >
              Relatórios anteriores
            </a>
            <a className={buttonVariants({ variant: "ghost" })} href="/enviar">
              Começar de novo
            </a>
          </div>
        </div>

        <nav
          aria-label="Etapas da geração"
          className="mx-auto w-full max-w-(--container-max) px-8"
        >
          <Separator />
          <ol
            className="stage-stepper grid grid-cols-4 gap-2 py-4 sm:gap-4"
            style={
              {
                "--stage-progress": `${(activeStage / stages.length) * 100}%`,
              } as CSSProperties
            }
          >
            {stages.map((stage) => (
              <li key={stage.number}>
                <a
                  aria-current={
                    stage.number === activeStage ? "step" : undefined
                  }
                  className={cn(
                    "stage-step block text-xs font-semibold",
                    stage.number === activeStage
                      ? "text-primary"
                      : "text-muted-foreground"
                  )}
                  href={stage.path}
                >
                  <span className="stage-number">{stage.number}</span>
                  <span className="hidden sm:inline">· </span>
                  <span className="stage-label">{stage.label}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>
      </header>

      <main className="mx-auto flex w-full max-w-(--container-max) min-w-0 flex-1 flex-col items-center px-8 py-14">
        {run ? (
          <GenerationRun
            run={run}
            errorDetail={errorDetail}
            onRefresh={() => void refreshRun(run.run_id)}
            onBackToRows={() => void handleBackToRows()}
          />
        ) : controlSheet ? (
          <WorkGroups
            key={controlSheet.sheet_id}
            data={controlSheet}
            status={status}
            errorDetail={errorDetail}
            onReplaceFile={handleFile}
            onGenerate={handleGenerate}
          />
        ) : retainedSheets.length > 1 ? (
          <RetainedSheetPicker
            sheets={retainedSheets}
            onSelect={(sheetId) => void handleRetainedSheet(sheetId)}
          />
        ) : restoringSheet ? (
          <p role="status" className="mt-10 text-sm text-muted-foreground">
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
              className="mt-10 grid w-full max-w-5xl grid-cols-3 gap-5"
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
      </main>

      <footer className="border-t border-border bg-canvas">
        <div className="mx-auto flex w-full max-w-(--container-max) items-center justify-between gap-8 px-8 py-5 text-xs text-muted-foreground">
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
          <p className="max-w-xl text-right">
            As planilhas enviadas e os arquivos de cada relatório são mantidos
            no servidor por sete dias. Nenhum dado do cliente é enviado a uma
            conta de terceiros.
          </p>
        </div>
      </footer>
    </div>
  )
}

export default App
