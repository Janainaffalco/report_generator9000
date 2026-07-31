import {
  CheckCircle2Icon,
  CircleIcon,
  LoaderCircleIcon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { BatchResponse, RunResponse } from "@/lib/runs"

interface BatchGenerationProps {
  batch: BatchResponse
  errorDetail: string | null
  onRefresh: () => void
  onOpenRun: (run: RunResponse) => void
  onBackToRows: () => void
}

const terminalOutcomes = new Set([
  "finished",
  "stopped",
  "rejected",
  "failed",
])

export function BatchGeneration({
  batch,
  errorDetail,
  onRefresh,
  onOpenRun,
  onBackToRows,
}: BatchGenerationProps) {
  const complete = batch.runs.every((run) => terminalOutcomes.has(run.outcome))

  return (
    <section className="mt-10 w-full max-w-4xl" aria-labelledby="batch-heading">
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
        Os relatórios são gerados um de cada vez. Você pode fechar esta aba e
        voltar depois.
      </p>
      {errorDetail && (
        <div className="mt-4 flex items-center gap-3">
          <p role="alert" className="text-sm text-destructive">
            {errorDetail}
          </p>
          <Button variant="secondary" size="sm" onClick={onRefresh}>
            Atualizar agora
          </Button>
        </div>
      )}
      <ol className="mt-8 flex flex-col gap-3">
        {batch.runs.map((run) => (
          <li key={run.run_id}>
            <RunCard run={run} onOpen={() => onOpenRun(run)} />
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

function RunCard({ run, onOpen }: { run: RunResponse; onOpen: () => void }) {
  const name = `${run.engagement.pasta} · ${run.engagement.razao_social}`
  const copy = outcomeCopy(run)
  const Icon = copy.icon

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="text-base">
            {run.engagement.razao_social}
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            {run.engagement.pasta}
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm font-medium">
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
        <CardContent className="flex items-start justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            {run.reason ?? `${name} está pronto para conferência.`}
          </p>
          {run.outcome === "finished" && (
            <Button size="sm" onClick={onOpen}>
              Conferir relatório
            </Button>
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
