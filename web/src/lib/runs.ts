export type RunOutcome =
  "queued" | "running" | "finished" | "stopped" | "rejected"
export type StageState = "pending" | "current" | "done"

export interface RunStage {
  name: string
  state: StageState
}

export interface RunResponse {
  run_id: string
  sheet_id: string
  engagement: {
    row_number: number
    pasta: string
    razao_social: string
  }
  outcome: RunOutcome
  current_stage: string | null
  stages: RunStage[]
  stage_history: string[]
  page_count: number | null
  status: string | null
  filename: string | null
  reason: string | null
  download_url: string | null
}

export interface BatchResponse {
  batch_id: string
  sheet_id: string
  runs: RunResponse[]
}

export type RunResult =
  | { ok: true; data: RunResponse }
  | { ok: false; detail: string; status?: number }

export type BatchResult =
  | { ok: true; data: BatchResponse }
  | { ok: false; detail: string; status?: number }

async function readResponse<T>(
  response: Response,
  fallback: string
): Promise<
  { ok: true; data: T } | { ok: false; detail: string; status?: number }
> {
  if (response.ok) {
    return { ok: true, data: (await response.json()) as T }
  }
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === "string") {
      return { ok: false, detail: body.detail, status: response.status }
    }
  } catch {
    // use the stable fallback below
  }
  return {
    ok: false,
    detail: fallback,
    status: response.status,
  }
}

export async function startRun(
  sheetId: string,
  rowNumber: number
): Promise<RunResult> {
  try {
    return readResponse<RunResponse>(
      await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheet_id: sheetId,
          row_number: rowNumber,
        }),
      }),
      "Não foi possível consultar esta geração. Tente novamente."
    )
  } catch {
    return {
      ok: false,
      detail: "Não foi possível iniciar a geração. Tente novamente.",
    }
  }
}

export async function getRun(runId: string): Promise<RunResult> {
  try {
    return readResponse<RunResponse>(
      await fetch(`/api/runs/${runId}`),
      "Não foi possível consultar esta geração. Tente novamente."
    )
  } catch {
    return {
      ok: false,
      detail: "Não foi possível atualizar a geração. Tentaremos de novo.",
    }
  }
}

export async function startBatch(
  sheetId: string,
  rowNumbers: number[]
): Promise<BatchResult> {
  try {
    return readResponse<BatchResponse>(
      await fetch("/api/batches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheet_id: sheetId,
          row_numbers: rowNumbers,
        }),
      }),
      "Não foi possível consultar este lote. Tente novamente."
    )
  } catch {
    return {
      ok: false,
      detail: "Não foi possível iniciar o lote. Tente novamente.",
    }
  }
}

export async function getBatch(batchId: string): Promise<BatchResult> {
  try {
    return readResponse<BatchResponse>(
      await fetch(`/api/batches/${batchId}`),
      "Não foi possível consultar este lote. Tente novamente."
    )
  } catch {
    return {
      ok: false,
      detail: "Não foi possível atualizar este lote. Tentaremos de novo.",
    }
  }
}
