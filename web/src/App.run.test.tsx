import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"
import type { BatchResponse, RunResponse } from "@/lib/runs"

function response(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

const base: RunResponse = {
  run_id: "persisted-run",
  sheet_id: "retained-sheet",
  engagement: {
    row_number: 2,
    pasta: "40-2026",
    razao_social: "DENISE BARROS DE ALMEIDA",
  },
  outcome: "running",
  current_stage: "capture",
  stages: [
    { name: "read_row", state: "done" },
    { name: "open_origin", state: "done" },
    { name: "derive_pages", state: "done" },
    { name: "capture", state: "current" },
    { name: "derive_palette", state: "pending" },
    { name: "capture_logo", state: "pending" },
    { name: "draft_prose", state: "pending" },
    { name: "assemble", state: "pending" },
    { name: "gate", state: "pending" },
  ],
  stage_history: ["read_row", "open_origin", "derive_pages"],
  page_count: 7,
  status: null,
  filename: null,
  reason: null,
  download_url: null,
}

const retainedSheet = {
  sheet_id: "retained-sheet",
  filename: "planilha enviada anteriormente.xlsx",
  engagements: [
    {
      row: { pasta: "40-2026", row_number: 2 },
      demanda: "011616/2026",
      razao_social: "DENISE BARROS DE ALMEIDA",
      especialista: "Especialista",
      kick_off: "15/04/2026",
      capture_origin: "https://example.test/",
      published_domain: null,
      report_ready_text: "",
    },
  ],
  stop_conditions: [],
  unsupported_rows: {
    total: 0,
    rows: [],
  },
}

describe("resumable generation screens", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/relatorios/persisted-run")
    vi.stubGlobal("fetch", vi.fn())
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    window.history.replaceState({}, "", "/")
  })

  it("reopens a progressing run directly from its URL", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response(base))

    render(<App />)

    await screen.findByText("Gerando agora")
    expect(fetch).toHaveBeenCalledWith("/api/runs/persisted-run")
    expect(screen.getByText("Lista de Páginas: 7 itens")).toBeInTheDocument()
  })

  it("reopens a progressing batch and shows what is running and queued", async () => {
    const batch: BatchResponse = {
      batch_id: "persisted-batch",
      sheet_id: "retained-sheet",
      runs: [
        base,
        {
          ...base,
          run_id: "queued-run",
          engagement: {
            row_number: 5,
            pasta: "41-2026",
            razao_social: "OUTRA EMPRESA LTDA",
          },
          outcome: "queued",
          current_stage: null,
          stages: base.stages.map((stage) => ({
            ...stage,
            state: "pending",
          })),
          stage_history: [],
          page_count: null,
        },
      ],
    }
    window.history.replaceState({}, "", "/lotes/persisted-batch")
    vi.mocked(fetch).mockResolvedValueOnce(response(batch))

    render(<App />)

    await screen.findByRole("heading", { name: "Lote em andamento" })
    expect(fetch).toHaveBeenCalledWith("/api/batches/persisted-batch")
    expect(screen.getByText("Gerando agora")).toBeInTheDocument()
    expect(screen.getByText("Na fila")).toBeInTheDocument()
    expect(screen.getByText("OUTRA EMPRESA LTDA")).toBeInTheDocument()
  })

  it("shows every batch outcome and opens a finished report for review", async () => {
    const finished: RunResponse = {
      ...base,
      outcome: "finished",
      current_stage: null,
      stages: base.stages.map((stage) => ({ ...stage, state: "done" })),
      status: "complete",
      filename:
        "RELATÓRIO TÉCNICO FINAL - 40-2026_DENISE BARROS DE ALMEIDA.docx",
      download_url: "/api/runs/persisted-run/download",
    }
    const secondFinished: RunResponse = {
      ...finished,
      run_id: "second-finished-run",
      engagement: {
        row_number: 5,
        pasta: "41-2026",
        razao_social: "OUTRA EMPRESA LTDA",
      },
      filename: "RELATÓRIO TÉCNICO FINAL - 41-2026_OUTRA EMPRESA LTDA.docx",
      download_url: "/api/runs/second-finished-run/download",
    }
    const batch: BatchResponse = {
      batch_id: "finished-batch",
      sheet_id: "retained-sheet",
      runs: [
        finished,
        secondFinished,
        {
          ...base,
          run_id: "stopped-run",
          outcome: "stopped",
          current_stage: null,
          reason: "Capture Origin indisponível",
        },
        {
          ...base,
          run_id: "rejected-run",
          outcome: "rejected",
          current_stage: null,
          reason: "block-integrity recusou o documento",
        },
      ],
    }
    const report = {
      run_id: finished.run_id,
      status: "complete",
      page_count: 1,
      filename: finished.filename,
      download_url: finished.download_url,
      pendencias: [],
      checks: [
        { label: "Nenhuma imagem de outro cliente no arquivo", passed: true },
      ],
    }
    const secondReport = {
      ...report,
      run_id: secondFinished.run_id,
      filename: secondFinished.filename,
      download_url: secondFinished.download_url,
    }
    window.history.replaceState({}, "", "/lotes/finished-batch")
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(batch))
      .mockResolvedValueOnce(response(report))
      .mockResolvedValueOnce(response(secondReport))

    render(<App />)

    await screen.findByRole("heading", { name: "Lote concluído" })
    expect(screen.getByText("Capture Origin indisponível")).toBeInTheDocument()
    expect(
      screen.getByText("block-integrity recusou o documento")
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getAllByRole("button", { name: "Conferir relatório" })[0]
    )

    expect(
      await screen.findByRole("heading", { name: "Revisão do relatório" })
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/relatorios/persisted-run")
    expect(fetch).toHaveBeenLastCalledWith("/api/runs/persisted-run/report")

    fireEvent.click(screen.getByRole("button", { name: "Voltar ao lote" }))
    expect(
      screen.getByRole("heading", { name: "Lote concluído" })
    ).toBeInTheDocument()
    const reviewButtons = screen.getAllByRole("button", {
      name: "Conferir relatório",
    })
    expect(reviewButtons).toHaveLength(2)
    fireEvent.click(reviewButtons[1])

    expect(
      await screen.findByText(secondFinished.filename!)
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/relatorios/second-finished-run")
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/runs/second-finished-run/report"
    )
  })

  it("shows an honest finished draft and its filename before download", async () => {
    const finished: RunResponse = {
      ...base,
      outcome: "finished",
      current_stage: null,
      stages: base.stages.map((stage) => ({ ...stage, state: "done" })),
      status: "draft",
      filename:
        "RELATÓRIO TÉCNICO FINAL - 40-2026_DENISE BARROS DE ALMEIDA.docx",
      download_url: "/api/runs/persisted-run/download",
    }
    const report = {
      run_id: "persisted-run",
      status: "draft",
      page_count: 5,
      filename: finished.filename,
      download_url: finished.download_url,
      pendencias: [
        {
          classification: "GATED",
          classification_label: "NÃO FORNECIDO",
          classification_explanation:
            "Normal e esperado: nenhuma automação consegue obter este conteúdo sozinha.",
          name: "logo do cliente",
          required_action: "Fornecer logo do cliente no valores.json",
          page: "documento",
        },
      ],
      checks: [
        { label: "Nenhuma imagem de outro cliente no arquivo", passed: true },
      ],
    }
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(finished))
      .mockResolvedValueOnce(response(report))

    render(<App />)

    expect(
      await screen.findByText("Rascunho com Pendências")
    ).toBeInTheDocument()
    expect(screen.getByText(finished.filename!)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Baixar .docx" })).toHaveAttribute(
      "href",
      finished.download_url
    )
    expect(screen.getByText("logo do cliente")).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith("/api/runs/persisted-run/report")
  })

  it("names a Stop Condition and offers the row list with no download", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response({
          ...base,
          outcome: "stopped",
          current_stage: null,
          reason: "STOP CONDITION: Capture Origin indisponível",
        })
      )
      .mockResolvedValueOnce(response(retainedSheet))

    render(<App />)

    await screen.findByText("A geração foi interrompida")
    expect(
      screen.getByText("STOP CONDITION: Capture Origin indisponível")
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole("button", { name: "Voltar à lista de trabalhos" })
    )
    await screen.findByText("Pronto para gerar")
    expect(fetch).toHaveBeenLastCalledWith("/api/control-sheet/retained-sheet")
    expect(window.location.pathname).toBe("/escolher")
    expect(
      screen.queryByRole("link", { name: "Baixar .docx" })
    ).not.toBeInTheDocument()
  })

  it("returns to the upload drop area when a run's sheet has expired", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response({
          ...base,
          outcome: "stopped",
          current_stage: null,
          reason: "STOP CONDITION: Capture Origin indisponível",
        })
      )
      .mockResolvedValueOnce(
        response(
          {
            detail:
              "Esta planilha expirou ou não é conhecida. Envie-a novamente.",
          },
          404
        )
      )

    render(<App />)

    await screen.findByText("A geração foi interrompida")
    fireEvent.click(
      screen.getByRole("button", { name: "Voltar à lista de trabalhos" })
    )

    expect(
      await screen.findByTestId("control-sheet-dropzone")
    ).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent(/expirou/i)
    expect(window.location.pathname).toBe("/enviar")
  })

  it("reports a gate rejection as a defect that produced nothing", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      response({
        ...base,
        outcome: "rejected",
        current_stage: null,
        reason: "block-integrity recusou o documento",
      })
    )

    render(<App />)

    await screen.findByText("A geração encontrou um defeito")
    expect(
      screen.getByText(/isso é um defeito da geração/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText("Nenhum documento foi produzido.")
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("link", { name: "Baixar .docx" })
    ).not.toBeInTheDocument()
  })
})
