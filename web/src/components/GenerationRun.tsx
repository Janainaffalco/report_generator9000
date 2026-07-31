import { CheckIcon, CircleIcon, LoaderCircleIcon } from "lucide-react"

import { ReviewScreen } from "@/components/ReviewScreen"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { RunResponse } from "@/lib/runs"
import { cn } from "@/lib/utils"

const stageCopy: Record<string, string> = {
  read_row: "Conferindo os dados do trabalho",
  open_origin: "Abrindo o site",
  derive_pages: "Descobrindo a Lista de Páginas",
  capture: "Capturando páginas, Cabeçalho e Rodapé",
  derive_palette: "Lendo as cores do site",
  capture_logo: "Capturando a marca do cliente",
  draft_prose: "Redigindo os dois textos do relatório",
  assemble: "Montando o documento a partir do Master",
  gate: "Conferindo a integridade do documento",
}

interface GenerationRunProps {
  run: RunResponse
  errorDetail: string | null
  onRefresh: () => void
  onBackToRows: () => void
  onBackToBatch?: () => void
}

export function GenerationRun({
  run,
  errorDetail,
  onRefresh,
  onBackToRows,
  onBackToBatch,
}: GenerationRunProps) {
  const name = `${run.engagement.pasta} · ${run.engagement.razao_social}`

  if (run.outcome === "finished") {
    return <ReviewScreen key={run.run_id} run={run} onBack={onBackToBatch} />
  }

  if (run.outcome === "stopped") {
    return (
      <TerminalCard
        title="A geração foi interrompida"
        name={name}
        explanation={
          run.reason ?? "Uma Stop Condition interrompeu este trabalho."
        }
        onBack={onBackToRows}
      />
    )
  }

  if (run.outcome === "rejected") {
    return (
      <TerminalCard
        title="A geração encontrou um defeito"
        name={name}
        explanation={
          run.reason ??
          "As conferências recusaram o documento antes da entrega."
        }
        defect
        onBack={onBackToRows}
      />
    )
  }

  return (
    <section className="mt-10 w-full max-w-3xl" aria-labelledby="run-heading">
      <p className="text-sm font-medium text-primary">Gerando agora</p>
      <h1 id="run-heading" className="mt-2 font-display text-3xl font-semibold">
        {name}
      </h1>
      <p className="mt-3 text-muted-foreground">
        Você pode fechar esta aba e voltar depois. A geração continua no
        servidor.
      </p>
      {run.page_count !== null && (
        <p className="mt-3 text-sm font-medium">
          Lista de Páginas: {run.page_count} itens
        </p>
      )}
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
        {run.stages.map((stage) => (
          <li
            key={stage.name}
            className={cn(
              "flex items-center gap-3 rounded-md border px-4 py-3",
              stage.state === "current" && "border-primary bg-primary/5"
            )}
          >
            {stage.state === "done" ? (
              <CheckIcon aria-hidden="true" className="size-5 text-primary" />
            ) : stage.state === "current" ? (
              <LoaderCircleIcon
                aria-hidden="true"
                className="size-5 animate-spin text-primary"
              />
            ) : (
              <CircleIcon
                aria-hidden="true"
                className="size-5 text-muted-foreground"
              />
            )}
            <span
              className={cn(
                "text-sm",
                stage.state === "current" && "font-medium"
              )}
            >
              {stageCopy[stage.name] ?? stage.name}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function TerminalCard({
  title,
  name,
  explanation,
  defect = false,
  onBack,
}: {
  title: string
  name: string
  explanation: string
  defect?: boolean
  onBack: () => void
}) {
  return (
    <Card className="mt-10 w-full max-w-3xl border-destructive/40">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="font-medium">{name}</p>
        <p className="text-sm text-muted-foreground">{explanation}</p>
        {defect && (
          <p className="text-sm font-medium text-destructive">
            Isso é um defeito da geração, não uma Pendência do relatório.
          </p>
        )}
        <p className="text-sm font-medium">Nenhum documento foi produzido.</p>
        <Button variant="secondary" className="self-start" onClick={onBack}>
          Voltar à lista de trabalhos
        </Button>
      </CardContent>
    </Card>
  )
}
