import { useState } from "react"
import { FileSpreadsheetIcon } from "lucide-react"

import { SheetFileInput } from "@/components/SheetFileInput"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Card, CardContent } from "@/components/ui/card"
import type {
  ControlSheetResponse,
  Engagement,
  StopCondition,
  UnsupportedRows,
} from "@/lib/control-sheet"
import { rowKey } from "@/lib/control-sheet"
import { cn } from "@/lib/utils"

interface WorkGroupsProps {
  data: ControlSheetResponse
  status: "idle" | "loading" | "starting"
  errorDetail: string | null
  onReplaceFile: (file: File) => void
  onGenerate: (rowNumber: number) => void
}

export function WorkGroups({
  data,
  status,
  errorDetail,
  onReplaceFile,
  onGenerate,
}: WorkGroupsProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const isLoading = status !== "idle"

  function toggle(key: string) {
    setSelected((previous) => (previous === key ? null : key))
  }

  const engagement = data.engagements.find(
    (item) => rowKey(item.row) === selected,
  )
  const generateLabel =
    status === "starting"
      ? "Iniciando geração…"
      : engagement
        ? "Gerar relatório"
        : "Selecione um trabalho"

  return (
    <div className="mt-10 flex w-full max-w-4xl min-w-0 flex-col gap-10">
      <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileSpreadsheetIcon aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-wide text-primary uppercase">
              Planilha enviada
            </p>
            <p className="truncate text-base font-semibold text-foreground">
              {data.filename}
            </p>
          </div>
        </div>
        <SheetFileInput
          label="Enviar outra planilha"
          size="sm"
          variant="secondary"
          disabled={isLoading}
          onFile={onReplaceFile}
        />
      </div>

      <p
        role="status"
        aria-live="polite"
        className="min-h-4 text-sm text-muted-foreground"
      >
        {status === "loading"
          ? "Lendo a planilha, isso pode levar um instante…"
          : ""}
      </p>
      {errorDetail && (
        <p role="alert" className="text-sm font-medium text-destructive">
          {errorDetail}
        </p>
      )}

      <ReadySection
        engagements={data.engagements}
        selected={selected}
        engagement={engagement}
        generateLabel={generateLabel}
        isLoading={isLoading}
        onToggle={toggle}
        onGenerate={onGenerate}
      />
      <StopConditionSection stopConditions={data.stop_conditions} />
      <UnsupportedSection unsupported={data.unsupported_rows} />
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate font-medium text-foreground">{value}</p>
    </div>
  )
}

interface ReadySectionProps {
  engagements: Engagement[]
  selected: string | null
  engagement: Engagement | undefined
  generateLabel: string
  isLoading: boolean
  onToggle: (key: string) => void
  onGenerate: (rowNumber: number) => void
}

function ReadySection({
  engagements,
  selected,
  engagement,
  generateLabel,
  isLoading,
  onToggle,
  onGenerate,
}: ReadySectionProps) {
  return (
    <section aria-labelledby="ready-heading" className="text-left">
      <div className="sticky top-0 z-10 -mx-2 flex items-center justify-between gap-4 border-b border-border/80 bg-background/95 px-2 py-3 backdrop-blur-sm">
        <h2
          id="ready-heading"
          className="font-display text-2xl font-semibold text-heading"
        >
          Pronto para gerar
        </h2>
        <Button
          size="lg"
          className="rounded-full"
          disabled={!engagement || isLoading}
          onClick={() =>
            engagement && onGenerate(engagement.row.row_number)
          }
        >
          {generateLabel}
        </Button>
      </div>
      {engagements.length === 0 ? (
        <p className="mt-3 text-base text-muted-foreground">
          Nenhuma linha desta planilha está pronta para gerar.
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {engagements.map((engagement) => {
            const key = rowKey(engagement.row)
            const checked = selected === key
            return (
              <li key={key}>
                <Card
                  className={cn(
                    "flex-row items-center gap-4 px-4 py-3",
                    checked && "border-primary"
                  )}
                >
                  <CardContent className="flex w-full min-w-0 items-center gap-4 px-0">
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => onToggle(key)}
                      aria-label={`Selecionar ${engagement.razao_social}, pasta ${engagement.row.pasta ?? "sem pasta"}, linha ${engagement.row.row_number}`}
                    />
                    <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                      <Field
                        label="Razão Social"
                        value={engagement.razao_social}
                      />
                      <Field
                        label="Link do site"
                        value={engagement.capture_origin}
                      />
                      <Field
                        label="Pasta"
                        value={engagement.row.pasta ?? "—"}
                      />
                      <Field label="Demanda" value={engagement.demanda} />
                      <Field
                        label="Especialista"
                        value={engagement.especialista}
                      />
                      <Field label="Início" value={engagement.kick_off} />
                      <Field
                        label="Relatório pronto?"
                        value={engagement.report_ready_text || "—"}
                      />
                    </div>
                  </CardContent>
                </Card>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function StopConditionSection({
  stopConditions,
}: {
  stopConditions: StopCondition[]
}) {
  return (
    <section aria-labelledby="stop-heading" className="text-left">
      <h2
        id="stop-heading"
        className="font-display text-2xl font-semibold text-heading"
      >
        Não dá para gerar
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Quando falta um dado, a gente prefere parar a inventar um valor.
      </p>
      {stopConditions.length === 0 ? (
        <p className="mt-3 text-base text-muted-foreground">
          Nenhuma linha desta planilha está travada por um dado faltando.
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {stopConditions.map((stop) => (
            <li key={rowKey(stop.row)}>
              <Card className="border-hairline-soft bg-muted/40 px-4 py-3">
                <CardContent className="px-0">
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant="outline">{stop.coluna}</Badge>
                    <span className="text-xs text-muted-foreground">
                      Pasta {stop.row.pasta ?? "—"} · linha{" "}
                      {stop.row.row_number}
                    </span>
                  </div>
                  <p className="mt-2 font-medium text-foreground">
                    {stop.problema}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {stop.solucao}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Relatório pronto?: {stop.report_ready_text || "—"}
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function UnsupportedSection({
  unsupported,
}: {
  unsupported: UnsupportedRows
}) {
  return (
    <section aria-labelledby="unsupported-heading" className="text-left">
      <h2
        id="unsupported-heading"
        className="font-display text-2xl font-semibold text-heading"
      >
        Ainda não suportado
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        São Demandas reais, mas ainda não existe um Master aprovado para
        gerar estes relatórios.
      </p>
      {unsupported.total === 0 ? (
        <p className="mt-3 text-base text-muted-foreground">
          Todos os Temas desta planilha já têm suporte.
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {unsupported.rows.map((item) => (
            <li key={rowKey(item.row)}>
              <Card className="border-hairline-soft bg-muted/40 px-4 py-3">
                <CardContent className="px-0">
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant="secondary">Tema sem suporte</Badge>
                    <span className="text-xs text-muted-foreground">
                      Pasta {item.row.pasta ?? "—"} · linha{" "}
                      {item.row.row_number}
                    </span>
                  </div>
                  <p className="mt-2 font-medium text-foreground">
                    {item.tema}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {item.explicacao}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Relatório pronto?: {item.report_ready_text || "—"}
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default WorkGroups
