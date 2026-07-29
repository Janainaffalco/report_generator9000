import { useRef } from "react"
import {
  CheckCircle2Icon,
  FileTextIcon,
  ShieldCheckIcon,
  UploadIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { buttonVariants, Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
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

function currentStage(pathname: string) {
  const stage = stages.find((item) => pathname.startsWith(item.path))
  return stage?.number ?? 1
}

export function App() {
  const fileInput = useRef<HTMLInputElement>(null)
  const activeStage = currentStage(window.location.pathname)

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
            <a
              className={buttonVariants({ variant: "ghost" })}
              href="/enviar"
            >
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
                  aria-current={stage.number === activeStage ? "step" : undefined}
                  className={cn(
                    "block text-xs font-medium",
                    stage.number === activeStage
                      ? "text-primary"
                      : "text-muted-foreground",
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
        <section className="flex w-full max-w-4xl flex-col items-center text-center">
          <p className="text-sm text-muted-foreground">Comece aqui</p>
          <h1 className="mt-4 max-w-3xl font-display text-[44px] leading-[1.15] font-bold tracking-[-0.8px] text-heading">
            Arraste sua planilha de controle. O resto é com a gente.
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-6 text-foreground">
            A gente lê a planilha, visita o site do cliente, monta o relatório no
            Master aprovado e devolve pronto para você conferir.
          </p>

          <div className="mt-10 flex min-h-80 w-full max-w-3xl flex-col items-center justify-center rounded-lg border border-border bg-canvas px-8 py-12">
            <div className="flex size-16 items-center justify-center rounded-full bg-muted">
              <UploadIcon aria-hidden="true" />
            </div>
            <h2 className="mt-5 font-display text-2xl font-semibold text-heading">
              Solte a planilha aqui
            </h2>
            <p className="mt-2 text-base text-foreground">
              ou clique para escolher o arquivo no seu computador
            </p>
            <div className="mt-5 flex items-center gap-3">
              <Badge variant="secondary">.xlsx</Badge>
              <span className="text-xs text-muted-foreground">
                aba “LV e Site” · a mesma planilha que você já usa
              </span>
            </div>
            <input
              ref={fileInput}
              aria-label="Arquivo de planilha"
              className="sr-only"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            />
            <Button
              className="mt-7 rounded-full"
              size="lg"
              onClick={() => fileInput.current?.click()}
            >
              Escolher planilha
            </Button>
          </div>
        </section>

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
                <p className="leading-5 text-muted-foreground">{description}</p>
              </CardContent>
            </Card>
          ))}
        </section>
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
