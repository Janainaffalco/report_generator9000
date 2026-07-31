export interface RowRef {
  pasta: string | null
  row_number: number
}

export interface Engagement {
  row: RowRef
  demanda: string
  razao_social: string
  especialista: string
  kick_off: string
  capture_origin: string
  published_domain: string | null
  report_ready_text: string
}

export interface StopCondition {
  row: RowRef
  coluna: string
  problema: string
  solucao: string
  cause: string
  report_ready_text: string
}

export interface UnsupportedRow {
  row: RowRef
  tema: string
  report_ready_text: string
  cause: string
  explicacao: string
}

export interface UnsupportedRows {
  total: number
  rows: UnsupportedRow[]
}

export interface ControlSheetResponse {
  sheet_id: string
  filename: string
  engagements: Engagement[]
  stop_conditions: StopCondition[]
  unsupported_rows: UnsupportedRows
}

export interface RetainedSheet {
  sheet_id: string
  filename: string
  uploaded_at: string
  ready_count: number
}

export type ControlSheetResult =
  { ok: true; data: ControlSheetResponse } | { ok: false; detail: string }

export type RetainedSheetsResult =
  { ok: true; data: RetainedSheet[] } | { ok: false; detail: string }

const GENERIC_ERROR_DETAIL =
  "Não foi possível ler essa planilha. Tente novamente."

export function rowKey(row: RowRef) {
  return `${row.pasta ?? ""}::${row.row_number}`
}

export async function uploadControlSheet(
  file: File
): Promise<ControlSheetResult> {
  const formData = new FormData()
  formData.append("file", file)

  let response: Response
  try {
    response = await fetch("/api/control-sheet", {
      method: "POST",
      body: formData,
    })
  } catch {
    return {
      ok: false,
      detail: "Não foi possível conectar ao servidor. Tente novamente.",
    }
  }

  if (response.ok) {
    const data = (await response.json()) as ControlSheetResponse
    return { ok: true, data }
  }

  let detail = GENERIC_ERROR_DETAIL
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === "string") {
      detail = body.detail
    }
  } catch {
    // keep the generic detail
  }
  return { ok: false, detail }
}

export async function getRetainedControlSheet(
  sheetId: string
): Promise<ControlSheetResult> {
  try {
    const response = await fetch(`/api/control-sheet/${sheetId}`)
    if (response.ok) {
      return {
        ok: true,
        data: (await response.json()) as ControlSheetResponse,
      }
    }
    const body = (await response.json()) as { detail?: unknown }
    return {
      ok: false,
      detail:
        typeof body.detail === "string" ? body.detail : GENERIC_ERROR_DETAIL,
    }
  } catch {
    return {
      ok: false,
      detail: "Não foi possível recuperar a planilha desta geração.",
    }
  }
}

export async function listRetainedControlSheets(): Promise<RetainedSheetsResult> {
  try {
    const response = await fetch("/api/control-sheets")
    if (response.ok) {
      return {
        ok: true,
        data: (await response.json()) as RetainedSheet[],
      }
    }
    return {
      ok: false,
      detail: "Não foi possível procurar planilhas enviadas anteriormente.",
    }
  } catch {
    return {
      ok: false,
      detail: "Não foi possível procurar planilhas enviadas anteriormente.",
    }
  }
}
