import { useState } from "react"
import { CheckCircle2Icon, FileTextIcon, ShieldCheckIcon } from "lucide-react"

import { UploadPanel } from "@/components/UploadPanel"
import { WorkGroups } from "@/components/WorkGroups"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import type { ControlSheetResponse } from "@/lib/control-sheet"
import { uploadControlSheet } from "@/lib/control-sheet"
import { cn } from "@/lib/utils"

const stages = [
  { number: 1, label: "Enviar planilha", path: "/enviar" },
  { number: 2, label: "Escolher o trabalho", path: "/escolher" },
  { number: 3, label: "Conferir o relatório", path: "/conferir" },
  { number: 4, label: "Baixar", path: "/baixar" },
]

const features = [
  {
    title: "Nada para configurar",
    description: "Sem login, sem conta, sem instalação. Abra e use.",
    icon: ShieldCheckIcon,
  },
  {
    title: "Só os trabalhos que dão para fazer",
    description:
      "Mostramos as linhas prontas para gerar e explicamos as que não estão.",
    icon: CheckCircle2Icon,
  },
  {
    title: "Documento Word no fim",
    description:
      "O .docx sai do Master aprovado, pronto para o seu ajuste final.",
    icon: FileTextIcon,
  },
]

const CHOOSING_WORK_PATH = "/escolher"

function currentStage(pathname: string) {
  const stage = stages.find((item) => pathname.startsWith(item.path))
  return stage?.number ?? 1
}

export function App() {
  const [status, setStatus] = useState<"idle" | "loading">("idle")
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [controlSheet, setControlSheet] = useState<ControlSheetResponse | null>(
    null
  )

  const activeStage = currentStage(
    controlSheet ? CHOOSING_WORK_PATH : window.location.pathname
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

  return (
    <div className="flex min-h-screen min-w-0 flex-col bg-background">
      <header className="border-b border-border bg-canvas">
        <div className="mx-auto flex w-full max-w-(--container-max) min-w-0 items-center justify-between gap-8 px-8 py-4">
          <div className="flex min-w-0 items-baseline gap-3">
            <span className="font-display text-xl font-bold text-primary">
              Relatórios
            </span>
            <span className="truncate text-sm text-muted-foreground">
              Relatório Técnico Final · SEBRAETEC
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-4">
            <span className="text-sm text-muted-foreground">
              sem cadastro · sem senha
            </span>
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
          <ol className="grid grid-cols-4 gap-4 py-4">
            {stages.map((stage) => (
              <li key={stage.number}>
                <a
                  aria-current={
                    stage.number === activeStage ? "step" : undefined
                  }
                  className={cn(
                    "block text-xs font-medium",
                    stage.number === activeStage
                      ? "text-primary"
                      : "text-muted-foreground"
                  )}
                  href={stage.path}
                >
                  {stage.number} · {stage.label}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      </header>

      <main className="mx-auto flex w-full max-w-(--container-max) min-w-0 flex-1 flex-col items-center px-8 py-14">
        {controlSheet ? (
          <WorkGroups
            key={controlSheet.sheet_id}
            data={controlSheet}
            status={status}
            errorDetail={errorDetail}
            onReplaceFile={handleFile}
          />
        ) : (
          <>
            <UploadPanel
              status={status}
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
          <p>
            Relatórios SEBRAETEC · gerados a partir do Master aprovado, sem
            alterar o layout
          </p>
          <p className="max-w-xl text-right">
            Os arquivos de cada execução são mantidos no servidor por sete dias.
            Nenhum dado do cliente é enviado a uma conta de terceiros.
          </p>
        </div>
      </footer>
    </div>
  )
}

export default App
