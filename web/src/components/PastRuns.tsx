import { DownloadIcon, FileClockIcon, SearchIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { PastRun } from "@/lib/runs"
import { cn } from "@/lib/utils"

type PastRunsProps = {
  runs: PastRun[]
  errorDetail: string | null
  onOpen: (run: PastRun) => void
}

function formatGeneratedAt(timestamp: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(timestamp))
}

export function PastRuns({ runs, errorDetail, onOpen }: PastRunsProps) {
  return (
    <section className="w-full max-w-6xl" aria-labelledby="past-runs-title">
      <div className="mb-8 flex items-start gap-4">
        <span className="rounded-full bg-secondary p-3 text-primary">
          <FileClockIcon aria-hidden="true" />
        </span>
        <div>
          <h1
            id="past-runs-title"
            className="font-display text-3xl font-bold text-heading"
          >
            Relatórios anteriores
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            Os relatórios ficam no servidor por sete dias para revisão e
            download. Depois desse prazo, é preciso gerá-los novamente a partir
            da planilha e do site. Nenhum dado do cliente é enviado a uma conta
            de terceiros.
          </p>
        </div>
      </div>

      {errorDetail && (
        <p role="alert" className="mb-6 text-sm text-destructive">
          {errorDetail}
        </p>
      )}

      {runs.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center py-14 text-center">
            <SearchIcon
              aria-hidden="true"
              className="mb-4 size-8 text-muted-foreground"
            />
            <p className="font-display text-lg font-semibold text-heading">
              Nenhum relatório anterior
            </p>
            <p className="mt-2 max-w-md text-sm text-muted-foreground">
              Quando um relatório ficar pronto, ele aparecerá aqui durante sete
              dias.
            </p>
          </CardContent>
        </Card>
      ) : (
        <ul className="grid gap-4" aria-label="Relatórios mantidos no servidor">
          {runs.map((run) => (
            <li key={run.run_id}>
              <Card>
                <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <CardTitle>{run.razao_social}</CardTitle>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Pasta {run.pasta} · Demanda {run.demanda}
                    </p>
                  </div>
                  <Badge
                    variant={
                      run.status === "complete" ? "default" : "secondary"
                    }
                  >
                    {run.status === "complete"
                      ? "Completo"
                      : "Rascunho com Pendências"}
                  </Badge>
                </CardHeader>
                <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
                  <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                    <div>
                      <dt className="text-muted-foreground">Gerado em</dt>
                      <dd>{formatGeneratedAt(run.generated_at)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Páginas</dt>
                      <dd>{run.page_count}</dd>
                    </div>
                  </dl>
                  <div className="flex flex-wrap gap-3">
                    <Button variant="secondary" onClick={() => onOpen(run)}>
                      Conferir relatório
                    </Button>
                    <a
                      className={cn(buttonVariants(), "gap-2")}
                      href={run.download_url}
                      download={run.filename}
                    >
                      <DownloadIcon aria-hidden="true" className="size-4" />
                      Baixar .docx
                    </a>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
