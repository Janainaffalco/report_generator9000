import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { App } from "@/App"

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

const pastRun = {
  run_id: "past-run",
  razao_social: "DENISE BARROS DE ALMEIDA",
  pasta: "40-2026",
  demanda: "011616/2026",
  generated_at: "2026-08-01T15:30:00-03:00",
  page_count: 5,
  status: "draft",
  filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_DENISE.docx",
  review_url: "/relatorios/past-run",
  download_url: "/api/runs/past-run/download",
  pdf_download_url: "/api/runs/past-run/download/pdf",
  pdf_filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_DENISE.pdf",
}

beforeEach(() => {
  window.history.replaceState({}, "", "/relatorios")
  vi.stubGlobal("fetch", vi.fn())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState({}, "", "/")
})

it("lists retained reports with direct review and download actions", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([pastRun]))

  render(<App />)

  expect(
    await screen.findByRole("heading", { name: "Relatórios anteriores" })
  ).toBeInTheDocument()
  expect(screen.getByText(pastRun.razao_social)).toBeInTheDocument()
  expect(screen.getByText(/Pasta 40-2026/)).toHaveTextContent(
    "Pasta 40-2026 · Demanda 011616/2026"
  )
  expect(screen.getByText("5")).toBeInTheDocument()
  expect(screen.getByText("Rascunho com Pendências")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Baixar .docx" })).toHaveAttribute(
    "href",
    pastRun.download_url
  )
  expect(screen.getByRole("link", { name: "Baixar .pdf" })).toHaveAttribute(
    "href",
    pastRun.pdf_download_url
  )
  expect(screen.getAllByText(/servidor por sete dias/i)).not.toHaveLength(0)
  expect(screen.getByText(/gerá-los novamente/i)).toBeInTheDocument()
  expect(screen.queryByText(/trinta dias/i)).not.toBeInTheDocument()
  expect(
    screen.queryByText(/nada sai deste computador/i)
  ).not.toBeInTheDocument()
})

it("states plainly when there are no past reports", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([]))

  render(<App />)

  expect(
    await screen.findByText("Nenhum relatório anterior")
  ).toBeInTheDocument()
})

it("omits the PDF download when a past run has no rendered PDF", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(
    response([{ ...pastRun, pdf_download_url: null, pdf_filename: null }])
  )

  render(<App />)

  await screen.findByRole("link", { name: "Baixar .docx" })
  expect(
    screen.queryByRole("link", { name: "Baixar .pdf" })
  ).not.toBeInTheDocument()
})

it("opens a past run in its review route", async () => {
  const run = {
    run_id: pastRun.run_id,
    sheet_id: "sheet-1",
    engagement: {
      row_number: 2,
      pasta: pastRun.pasta,
      razao_social: pastRun.razao_social,
    },
    outcome: "finished",
    current_stage: null,
    stages: [],
    stage_history: [],
    page_count: 5,
    status: "draft",
    filename: pastRun.filename,
    reason: null,
    download_url: pastRun.download_url,
    pdf_download_url: pastRun.pdf_download_url,
  }
  vi.mocked(fetch)
    .mockResolvedValueOnce(response([pastRun]))
    .mockResolvedValueOnce(response(run))
    .mockResolvedValueOnce(
      response({
        run_id: pastRun.run_id,
        status: "draft",
        page_count: 5,
        filename: pastRun.filename,
        download_url: pastRun.download_url,
        pendencias: [],
        checks: [],
      })
    )

  render(<App />)
  fireEvent.click(
    await screen.findByRole("button", { name: "Conferir relatório" })
  )

  expect(
    await screen.findByRole("heading", { name: "Revisão do relatório" })
  ).toBeInTheDocument()
  expect(window.location.pathname).toBe(pastRun.review_url)
  expect(fetch).toHaveBeenCalledWith("/api/runs/past-run")
})
