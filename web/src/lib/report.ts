export type PendenciaClass = "GATED" | "TOOL_BLOCKED" | "UNDECLARED" | "REVIEW"

export interface Pendencia {
  classification: PendenciaClass
  classification_label: string
  classification_explanation: string
  name: string
  required_action: string
  page: string
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
