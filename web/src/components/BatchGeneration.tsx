import { useEffect, useState } from "react"
import {
  CheckCircle2Icon,
  CircleIcon,
  DownloadIcon,
  Grid2X2Icon,
  ListIcon,
  LoaderCircleIcon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"

import { InlineNotice } from "@/components/InlineNotice"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { BatchResponse, RunResponse } from "@/lib/runs"
import { cn } from "@/lib/utils"

interface BatchGenerationProps {
  batch: BatchResponse
  errorDetail: string | null
  onRefresh: () => void
  onOpenRun: (run: RunResponse) => void
  onBackToRows: () => void
}

const terminalOutcomes = new Set(["finished", "stopped", "rejected", "failed"])

type BatchLayout = "list" | "grid"

const BATCH_LAYOUT_KEY = "report-generator:batch-layout"

function initialLayout(): BatchLayout {
  try {
    return window.localStorage.getItem(BATCH_LAYOUT_KEY) === "grid"
      ? "grid"
      : "list"
  } catch {
    return "list"
  }
}

export function BatchGeneration({
  batch,
  errorDetail,
  onRefresh,
  onOpenRun,
  onBackToRows,
}: BatchGenerationProps) {
  const [layout, setLayout] = useState<BatchLayout>(initialLayout)
  const complete = batch.runs.every((run) => terminalOutcomes.has(run.outcome))
  const finishedCount = batch.runs.filter(
    (run) => run.outcome === "finished"
  ).length

  useEffect(() => {
    try {
      window.localStorage.setItem(BATCH_LAYOUT_KEY, layout)
    } catch {
      // The preference is optional when storage is unavailable.
    }
  }, [layout])

  return (
    <section className="mt-10 w-full max-w-6xl" aria-labelledby="batch-heading">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-primary">
            {complete ? "Geração encerrada" : "Geração sequencial"}
          </p>
          <h1
            id="batch-heading"
            className="mt-2 font-display text-3xl font-semibold"
          >
            {complete ? "Lote concluído" : "Lote em andamento"}
          </h1>
          <p className="mt-3 text-muted-foreground">
            {finishedCount} de {batch.runs.length}{" "}
            {batch.runs.length === 1
              ? "relatório pronto"
              : "relatórios prontos"}
            .
            {!complete &&
              " A geração continua no servidor mesmo se você fechar esta aba."}
          </p>
        </div>

        <div
          className="flex w-fit items-center gap-1 rounded-md border border-border bg-canvas p-1"
          aria-label="Layout da fila"
          role="group"
        >
          <Button
            size="sm"
            variant={layout === "list" ? "secondary" : "ghost"}
            aria-pressed={layout === "list"}
            onClick={() => setLayout("list")}
          >
            <ListIcon aria-hidden="true" />
            Lista
          </Button>
          <Button
            size="sm"
            variant={layout === "grid" ? "secondary" : "ghost"}
            aria-pressed={layout === "grid"}
            onClick={() => setLayout("grid")}
          >
            <Grid2X2Icon aria-hidden="true" />
            Grade
          </Button>
        </div>
      </div>

      {errorDetail && (
        <InlineNotice
          tone="error"
          title="Não foi possível atualizar o lote"
          action={{ label: "Atualizar agora", onClick: onRefresh }}
          className="mt-4"
        >
          {errorDetail}
        </InlineNotice>
      )}

      <ol
        aria-label="Fila de relatórios"
        className={cn(
          "mt-8 grid gap-3",
          layout === "grid"
            ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-3"
            : "grid-cols-1"
        )}
        data-layout={layout}
      >
        {batch.runs.map((run) => (
          <li key={run.run_id}>
            <RunCard run={run} layout={layout} onOpen={() => onOpenRun(run)} />
          </li>
        ))}
      </ol>

      {complete && (
        <Button className="mt-6" variant="secondary" onClick={onBackToRows}>
          Voltar à lista de trabalhos
        </Button>
      )}
    </section>
  )
}

function RunCard({
  run,
  layout,
  onOpen,
}: {
  run: RunResponse
  layout: BatchLayout
  onOpen: () => void
}) {
  const name = `${run.engagement.pasta} · ${run.engagement.razao_social}`
  const copy = outcomeCopy(run)
  const Icon = copy.icon

  return (
    <Card className="h-full">
      <CardHeader
        className={cn(
          "gap-4",
          layout === "list"
            ? "flex-row items-start justify-between"
            : "grid-cols-1"
        )}
      >
        <div className="min-w-0">
          <CardTitle className="text-base">
            {run.engagement.razao_social}
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            {run.engagement.pasta}
          </p>
        </div>
        <div
          className={cn(
            "flex w-fit shrink-0 items-center gap-2 rounded-full px-2.5 py-1 text-xs font-semibold",
            run.outcome === "finished"
              ? "bg-[var(--success-pale)] text-[var(--success-deep)]"
              : run.outcome === "running"
                ? "bg-primary/8 text-primary"
                : "bg-secondary text-secondary-foreground"
          )}
        >
          <Icon
            aria-hidden="true"
            className={
              run.outcome === "running" ? "size-4 animate-spin" : "size-4"
            }
          />
          <span>{copy.label}</span>
        </div>
      </CardHeader>

      {(run.reason || run.outcome === "finished") && (
        <CardContent
          className={cn(
            "flex flex-1 gap-4",
            layout === "list"
              ? "flex-col items-start sm:flex-row sm:justify-between"
              : "flex-col"
          )}
        >
          <p className="min-w-0 flex-1 text-sm text-muted-foreground">
            {run.reason ?? `${name} está pronto para conferência.`}
          </p>
          {run.outcome === "finished" && run.download_url && (
            <div
              className={cn(
                "flex shrink-0 flex-wrap gap-2",
                layout === "grid" && "mt-auto w-full"
              )}
            >
              <a
                className={cn(
                  buttonVariants({ size: "sm" }),
                  layout === "grid" && "flex-1"
                )}
                href={run.download_url}
                download
              >
                <DownloadIcon aria-hidden="true" />
                Baixar relatório
              </a>
              <Button
                size="sm"
                variant="secondary"
                className={cn(layout === "grid" && "flex-1")}
                onClick={onOpen}
              >
                Conferir relatório
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}

function outcomeCopy(run: RunResponse) {
  if (run.outcome === "queued") {
    return { label: "Na fila", icon: CircleIcon }
  }
  if (run.outcome === "running") {
    return { label: "Gerando agora", icon: LoaderCircleIcon }
  }
  if (run.outcome === "finished") {
    return { label: "Relatório pronto", icon: CheckCircle2Icon }
  }
  if (run.outcome === "stopped") {
    return { label: "Stop Condition", icon: OctagonXIcon }
  }
  if (run.outcome === "failed") {
    return { label: "Falha na geração", icon: TriangleAlertIcon }
  }
  return { label: "Recusado pelos gates", icon: OctagonXIcon }
}
