export type PendenciaClass = "GATED" | "TOOL_BLOCKED" | "UNDECLARED" | "REVIEW"

export interface Pendencia {
  classification: PendenciaClass
  classification_label: string
  classification_explanation: string
  name: string
  required_action: string
  page: string
  preview_page: number | null
  attachment_filename: string | null
  attachment_value_key: string | null
}

export async function attachGatedInputs(runId: string, files: File[]) {
  const body = new FormData()
  files.forEach((file) => body.append("files", file))
  try {
    const response = await fetch(`/api/runs/${runId}/attachments`, {
      method: "POST",
      body,
    })
    const data = await response.json()
    return response.ok
      ? { ok: true as const, data }
      : { ok: false as const, detail: data.detail as string }
  } catch {
    return {
      ok: false as const,
      detail: "Não foi possível anexar os arquivos.",
    }
  }
}

export interface Check {
  label: string
  passed: boolean
}

export interface FinishedReport {
  run_id: string
  status: string
  /** Pages of the generated document — what the review screen pages through. */
  page_count: number
  filename: string
  download_url: string
  pdf_filename: string | null
  pdf_download_url: string | null
  pendencias: Pendencia[]
  checks: Check[]
}

export type ReportResult =
  { ok: true; data: FinishedReport } | { ok: false; detail: string }

export function previewPageUrl(runId: string, page: number): string {
  return `/api/runs/${runId}/previews/${page}`
}

export async function getReport(runId: string): Promise<ReportResult> {
  try {
    const response = await fetch(`/api/runs/${runId}/report`)
    if (response.ok) {
      return { ok: true, data: (await response.json()) as FinishedReport }
    }
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === "string") {
        return { ok: false, detail: body.detail }
      }
    } catch {
      // use the stable fallback below
    }
    return {
      ok: false,
      detail: "Não foi possível carregar o relatório. Tente novamente.",
    }
  } catch {
    return {
      ok: false,
      detail: "Não foi possível carregar o relatório. Tente novamente.",
    }
  }
}
