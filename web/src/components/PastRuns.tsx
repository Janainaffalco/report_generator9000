import { DownloadIcon, FileClockIcon } from "lucide-react"

import { EmptyStep, type EmptyStepPath } from "@/components/EmptyStep"
import { InlineNotice } from "@/components/InlineNotice"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { PastRun } from "@/lib/runs"
import { cn } from "@/lib/utils"

type PastRunsProps = {
  runs: PastRun[]
  errorDetail: string | null
  emptyPaths: EmptyStepPath[]
  onOpen: (run: PastRun) => void
}

function formatGeneratedAt(timestamp: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(timestamp))
}

export function PastRuns({
  runs,
  errorDetail,
  emptyPaths,
  onOpen,
}: PastRunsProps) {
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
        <InlineNotice
          tone="error"
          title="Não foi possível abrir o relatório"
          className="mb-6"
        >
          {errorDetail}
        </InlineNotice>
      )}

      {runs.length === 0 ? (
        <div className="flex justify-center">
          <EmptyStep
            headingLevel={2}
            title="Nenhum relatório anterior"
            description="Quando um relatório ficar pronto, ele aparecerá aqui durante sete dias."
            paths={emptyPaths}
          />
        </div>
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
                    {run.pdf_download_url && (
                      <a
                        className={cn(
                          buttonVariants({ variant: "secondary" }),
                          "gap-2"
                        )}
                        href={run.pdf_download_url}
                        download={run.pdf_filename ?? undefined}
                      >
                        <DownloadIcon aria-hidden="true" className="size-4" />
                        Baixar .pdf
                      </a>
                    )}
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
