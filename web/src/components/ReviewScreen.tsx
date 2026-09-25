import { useEffect, useState } from "react"
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  EyeIcon,
  HelpCircleIcon,
  InboxIcon,
  PaletteIcon,
  SearchIcon,
  XCircleIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { attachGatedInputs, getReport, previewPageUrl } from "@/lib/report"
import type { FinishedReport, Pendencia, PendenciaClass } from "@/lib/report"
import type { RunResponse } from "@/lib/runs"
import { cn } from "@/lib/utils"

interface ReviewScreenProps {
  run: RunResponse
  onBack?: () => void
  onRegenerated?: (run: RunResponse) => void
}

const CLASS_STYLE: Record<
  PendenciaClass,
  { badge: "secondary" | "destructive" | "outline"; icon: typeof InboxIcon }
> = {
  GATED: { badge: "secondary", icon: InboxIcon },
  TOOL_BLOCKED: { badge: "destructive", icon: AlertTriangleIcon },
  UNDECLARED: { badge: "outline", icon: PaletteIcon },
  REVIEW: { badge: "outline", icon: EyeIcon },
  INCONCLUSIVO: { badge: "outline", icon: SearchIcon },
}

// A class the frontend does not know must not borrow another one's meaning:
// showing it as REVIEW would tell the consultant it awaits their approval,
// which may be untrue. Carry it neutrally instead and let its own label speak.
const UNKNOWN_CLASS_STYLE = {
  badge: "outline",
  icon: HelpCircleIcon,
} as const

export function ReviewScreen({
  run,
  onBack,
  onRegenerated,
}: ReviewScreenProps) {
  const [report, setReport] = useState<FinishedReport | null>(null)
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [attachments, setAttachments] = useState<File[]>([])
  const [attachmentMatches, setAttachmentMatches] = useState(
    new Map<string, string[]>()
  )
  const [attaching, setAttaching] = useState(false)

  useEffect(() => {
    let cancelled = false
    void getReport(run.run_id).then((result) => {
      if (cancelled) {
        return
      }
      if (result.ok) {
        setReport(result.data)
        setCurrentPage(1)
      } else {
        setErrorDetail(result.detail)
      }
    })
    return () => {
      cancelled = true
    }
  }, [run.run_id])

  if (errorDetail) {
    return (
      <section
        className="mt-10 w-full max-w-3xl"
        aria-labelledby="review-error"
      >
        <h1 id="review-error" className="font-display text-2xl font-semibold">
          Não foi possível carregar a revisão
        </h1>
        <p role="alert" className="mt-3 text-sm text-destructive">
          {errorDetail}
        </p>
      </section>
    )
  }

  if (!report) {
    return (
      <section className="mt-10 w-full max-w-3xl" aria-live="polite">
        <p className="text-muted-foreground">Carregando revisão…</p>
      </section>
    )
  }

  const readyForSignature = report.pendencias.length === 0
  const statusLabel =
    report.status === "complete"
      ? "Completo"
      : report.status === "draft"
        ? "Rascunho com Pendências"
        : report.status
  const attachmentTargets = report.pendencias.reduce((targets, item) => {
    if (item.attachment_filename && !item.attachment_value_key) {
      const names = targets.get(item.attachment_filename) ?? []
      targets.set(item.attachment_filename, [...names, item.name])
    }
    return targets
  }, new Map<string, string[]>())
  const valueAttachmentTargets = report.pendencias.filter(
    (item) => item.attachment_value_key
  )

  async function selectAttachments(files: File[]) {
    const matches = new Map(attachmentTargets)
    const valuesFile = files.find((file) => file.name === "valores.json")
    if (valuesFile) {
      try {
        const values = JSON.parse(await valuesFile.text()) as Record<
          string,
          unknown
        >
        matches.set(
          valuesFile.name,
          valueAttachmentTargets
            .filter(
              (item) =>
                item.attachment_value_key && item.attachment_value_key in values
            )
            .map((item) => item.name)
        )
      } catch {
        matches.set(valuesFile.name, [])
      }
    }
    setAttachments(files)
    setAttachmentMatches(matches)
  }

  async function regenerate() {
    setAttaching(true)
    setErrorDetail(null)
    const result = await attachGatedInputs(run.run_id, attachments)
    setAttaching(false)
    if (!result.ok) {
      setErrorDetail(result.detail)
      return
    }
    onRegenerated?.(result.data as RunResponse)
  }

  return (
    <>
      {onBack && (
        <div className="mt-4 flex w-full justify-start">
          <Button variant="secondary" onClick={onBack}>
            Voltar ao lote
          </Button>
        </div>
      )}
      <section
        className="mt-10 grid w-full min-w-0 gap-6"
        style={{ gridTemplateColumns: "112px minmax(0, 1fr) 340px" }}
        aria-labelledby="review-heading"
      >
        <h1 id="review-heading" className="sr-only">
          Revisão do relatório
        </h1>

        <nav aria-label="Páginas do documento" className="min-w-0">
          <ol className="flex flex-col gap-2">
            {Array.from(
              { length: report.page_count },
              (_, index) => index + 1
            ).map((page) => (
              <li key={page}>
                <button
                  type="button"
                  aria-current={page === currentPage ? "page" : undefined}
                  onClick={() => setCurrentPage(page)}
                  className={cn(
                    "block w-full overflow-hidden rounded-sm border-2",
                    page === currentPage ? "border-primary" : "border-border"
                  )}
                >
                  <img
                    src={previewPageUrl(run.run_id, page)}
                    alt={`Página ${page}`}
                    loading="lazy"
                    className="aspect-[1240/1754] w-full object-cover"
                  />
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <div className="flex min-w-0 flex-col items-center gap-3">
          <div className="preview-frame w-full max-w-md overflow-hidden rounded-sm bg-canvas">
            <img
              src={previewPageUrl(run.run_id, currentPage)}
              alt={`Prévia da página ${currentPage} do relatório`}
              className="aspect-[1240/1754] w-full object-cover"
            />
          </div>
          <p className="text-sm font-medium">
            Página {currentPage} de {report.page_count}
          </p>
          <p className="max-w-md text-center text-xs text-muted-foreground">
            Páginas do PDF gerado a partir deste .docx.
          </p>
        </div>

        <div className="flex min-w-0 flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>{statusLabel}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                {readyForSignature
                  ? "Nenhuma Pendência foi encontrada — o relatório está pronto para assinatura."
                  : `Ainda há ${report.pendencias.length} ${
                      report.pendencias.length === 1
                        ? "Pendência"
                        : "Pendências"
                    } antes do envio ao cliente.`}
              </p>
              <p className="text-sm font-medium">{report.filename}</p>
              <p className="text-sm text-muted-foreground">
                {report.page_count === 1
                  ? "1 página"
                  : `${report.page_count} páginas`}
              </p>
              <div className="flex flex-wrap gap-2">
                <a
                  className={cn(buttonVariants({ size: "lg" }))}
                  href={report.download_url}
                  download={report.filename}
                >
                  Baixar .docx
                </a>
                {report.pdf_download_url && (
                  <a
                    className={cn(
                      buttonVariants({ size: "lg", variant: "secondary" })
                    )}
                    href={report.pdf_download_url}
                    download={report.pdf_filename ?? undefined}
                  >
                    Baixar .pdf
                  </a>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Pendências</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {report.pendencias.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nenhuma Pendência — o relatório está pronto para assinatura.
                </p>
              ) : (
                <>
                  <p className="text-xs text-muted-foreground">
                    Estas Pendências podem ser resolvidas agora ou depois,
                    direto no Word.
                  </p>
                  <ul className="flex flex-col gap-3">
                    {report.pendencias.map((pendencia, index) => (
                      <PendenciaItem
                        key={index}
                        pendencia={pendencia}
                        onNavigate={setCurrentPage}
                      />
                    ))}
                  </ul>
                  {attachmentTargets.size > 0 && (
                    <div className="flex flex-col gap-3 border-t pt-4">
                      <label
                        className="text-sm font-medium"
                        htmlFor="gated-files"
                      >
                        Anexar itens disponíveis
                      </label>
                      <input
                        id="gated-files"
                        type="file"
                        multiple
                        onChange={(event) =>
                          void selectAttachments(
                            Array.from(event.target.files ?? [])
                          )
                        }
                      />
                      <ul className="text-xs text-muted-foreground">
                        {attachments.map((file) => (
                          <li key={file.name}>
                            {file.name} →{" "}
                            {attachmentMatches.get(file.name)?.join(", ") ||
                              "nenhuma Pendência correspondente"}
                          </li>
                        ))}
                      </ul>
                      <Button
                        disabled={attachments.length === 0 || attaching}
                        onClick={() => void regenerate()}
                      >
                        {attaching ? "Anexando…" : "Anexar e gerar novamente"}
                      </Button>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Conferências automáticas</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-2">
                {report.checks.map((check) => (
                  <li
                    key={check.label}
                    className="flex items-center gap-2 text-sm"
                  >
                    {check.passed ? (
                      <CheckCircle2Icon
                        aria-hidden="true"
                        className="size-4 shrink-0 text-primary"
                      />
                    ) : (
                      <XCircleIcon
                        aria-hidden="true"
                        className="size-4 shrink-0 text-destructive"
                      />
                    )}
                    <span>{check.label}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </section>
    </>
  )
}

function PendenciaItem({
  pendencia,
  onNavigate,
}: {
  pendencia: Pendencia
  onNavigate: (page: number) => void
}) {
  const style = CLASS_STYLE[pendencia.classification] ?? UNKNOWN_CLASS_STYLE
  const Icon = style.icon
  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium">{pendencia.name}</p>
        <Badge variant={style.badge} className="gap-1">
          <Icon
            aria-hidden="true"
            data-icon="inline-start"
            className="size-3"
          />
          {pendencia.classification_label}
        </Badge>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        {pendencia.classification_explanation}
      </p>
      <p className="mt-2 text-sm">{pendencia.required_action}</p>
      {pendencia.preview_page === null ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Local no documento: {pendencia.page}
        </p>
      ) : (
        <button
          type="button"
          className="mt-1 text-left text-xs font-medium text-primary active:underline"
          onClick={() => onNavigate(pendencia.preview_page!)}
        >
          Página {pendencia.preview_page} · clique para ver no documento
        </button>
      )}
    </li>
  )
}
