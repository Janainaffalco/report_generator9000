export type RunOutcome = "running" | "finished" | "stopped" | "rejected"
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

export type RunResult =
  | { ok: true; data: RunResponse }
  | { ok: false; detail: string; status?: number }

async function readRunResponse(response: Response): Promise<RunResult> {
  if (response.ok) {
    return { ok: true, data: (await response.json()) as RunResponse }
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
    detail: "Não foi possível consultar esta geração. Tente novamente.",
    status: response.status,
  }
}

export async function startRun(
  sheetId: string,
  rowNumber: number
): Promise<RunResult> {
  try {
    return readRunResponse(
      await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sheet_id: sheetId,
          row_number: rowNumber,
        }),
      })
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
    return readRunResponse(await fetch(`/api/runs/${runId}`))
  } catch {
    return {
      ok: false,
      detail: "Não foi possível atualizar a geração. Tentaremos de novo.",
    }
  }
}
