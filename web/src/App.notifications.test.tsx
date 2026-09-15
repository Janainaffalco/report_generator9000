import "@testing-library/jest-dom/vitest"

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"
import type { RunResponse } from "@/lib/runs"

vi.mock("@/lib/session", () => ({
  getSession: vi.fn(async () => true),
  login: vi.fn(),
  logout: vi.fn(),
}))

function response(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

const running: RunResponse = {
  run_id: "persisted-run",
  sheet_id: "retained-sheet",
  engagement: {
    row_number: 2,
    pasta: "40-2026",
    razao_social: "DENISE BARROS DE ALMEIDA",
  },
  outcome: "running",
  current_stage: "capture",
  stages: [{ name: "capture", state: "current" }],
  stage_history: [],
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
  unsupported_rows: { total: 0, rows: [] },
}

function notifications() {
  return within(screen.getByRole("region", { name: "Notificações" }))
}

describe("free movement, empty states and notifications", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn())
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    window.localStorage.clear()
    window.history.replaceState({}, "", "/")
  })

  it("opens the review step with nothing generated and points back to the start", async () => {
    window.history.replaceState({}, "", "/conferir")

    render(<App />)

    expect(
      await screen.findByRole("heading", {
        name: "Nenhum relatório em conferência",
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "Em conferência" })
    ).toHaveAttribute("aria-current", "page")

    fireEvent.click(screen.getByRole("button", { name: /Enviar a planilha/ }))

    expect(
      await screen.findByTestId("control-sheet-dropzone")
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/")
    expect(fetch).not.toHaveBeenCalled()
  })

  it("shows an empty work step when no sheet is retained", async () => {
    window.history.replaceState({}, "", "/escolher")
    vi.mocked(fetch).mockResolvedValueOnce(response([]))

    render(<App />)

    expect(
      await screen.findByRole("heading", { name: "Nenhuma planilha carregada" })
    ).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith("/api/control-sheets")
  })

  it("announces a recovered sheet", async () => {
    window.history.replaceState({}, "", "/")
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response([
          {
            sheet_id: retainedSheet.sheet_id,
            filename: retainedSheet.filename,
            uploaded_at: "2026-07-30T18:00:00+00:00",
            ready_count: 1,
          },
        ])
      )
      .mockResolvedValueOnce(response(retainedSheet))

    render(<App />)

    expect(
      await notifications().findByText("Planilha recuperada")
    ).toBeInTheDocument()
    expect(
      notifications().getByText(
        "planilha enviada anteriormente.xlsx · 1 trabalho pronto para gerar"
      )
    ).toBeInTheDocument()
  })

  it("tells the consultant on another step that their report is ready", async () => {
    window.history.replaceState({}, "", "/relatorios/persisted-run")
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(running))
      .mockResolvedValueOnce(
        response({
          ...running,
          outcome: "finished",
          current_stage: null,
          status: "complete",
          filename: "relatorio.docx",
          download_url: "/api/runs/persisted-run/download",
        })
      )
      .mockResolvedValue(
        response({
          run_id: "persisted-run",
          status: "complete",
          page_count: 7,
          filename: "relatorio.docx",
          download_url: "/api/runs/persisted-run/download",
          pendencias: [],
          checks: [],
        })
      )

    render(<App />)

    await screen.findByText("Gerando agora")
    expect(
      screen.getByRole("link", { name: "Em conferência" })
    ).toHaveAccessibleDescription("Geração em andamento")
    fireEvent.click(screen.getByRole("link", { name: "Planilha" }))
    expect(window.location.pathname).toBe("/")

    const openReview = await notifications().findByRole(
      "button",
      { name: "Conferir" },
      { timeout: 4000 }
    )
    expect(notifications().getByText("Relatório gerado")).toBeInTheDocument()
    expect(
      notifications().getByText("Pasta 40-2026 — DENISE BARROS DE ALMEIDA")
    ).toBeInTheDocument()

    fireEvent.click(openReview)

    expect(window.location.pathname).toBe("/relatorios/persisted-run")
    expect(
      screen.getByRole("link", { name: "Em conferência" })
    ).toHaveAttribute("aria-current", "page")
    expect(
      screen.getByRole("link", { name: "Em conferência" })
    ).not.toHaveAccessibleDescription()
  })

  it("offers a retry when past reports fail to load", async () => {
    window.history.replaceState({}, "", "/relatorios")
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response({ detail: "Servidor indisponível." }, 503)
      )
      .mockResolvedValueOnce(response([]))

    render(<App />)

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Servidor indisponível."
    )

    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }))

    expect(
      await screen.findByText("Nenhum relatório anterior")
    ).toBeInTheDocument()
  })
})
