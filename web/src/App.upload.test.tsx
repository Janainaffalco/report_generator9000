import "@testing-library/jest-dom/vitest"

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"
import type { ControlSheetResponse } from "@/lib/control-sheet"

vi.mock("@/lib/session", () => ({
  getSession: vi.fn(async () => true),
  login: vi.fn(),
  logout: vi.fn(),
}))
import type { BatchResponse, RunResponse } from "@/lib/runs"

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

function makeFile(name = "Planilha para controle de relatorios.xlsx") {
  return new File(["conteudo"], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  })
}

const fixture: ControlSheetResponse = {
  sheet_id: "8f1c1111-2222-3333-4444-555566667777",
  filename: "Planilha para controle de relatorios.xlsx",
  engagements: [
    {
      row: { pasta: "40-2026", row_number: 2 },
      demanda: "011616/2026",
      razao_social: "DENISE BARROS DE ALMEIDA",
      especialista: "Bruno Henrique Santana Leal",
      kick_off: "15/04/2026",
      capture_origin: "https://denise.example/",
      published_domain: null,
      report_ready_text: "Prazo prorrogado",
    },
    {
      row: { pasta: "40-2026", row_number: 5 },
      demanda: "011700/2026",
      razao_social: "OUTRA EMPRESA LTDA",
      especialista: "Ana Paula Ferreira",
      kick_off: "20/04/2026",
      capture_origin: "https://outra.example/",
      published_domain: null,
      report_ready_text: "ok enviado",
    },
  ],
  stop_conditions: [
    {
      row: { pasta: null, row_number: 8 },
      demanda: "011800/2026",
      razao_social: "EMPRESA COM DADO PENDENTE LTDA",
      especialista: "Bruno Henrique Santana Leal",
      kick_off: "25/04/2026",
      link: "https://pendente.example/",
      coluna: "nº da pasta",
      problema: "A coluna nº da pasta está vazia.",
      solucao: "Preencha o número da pasta, como 115-2026.",
      cause: "Pasta is absent",
      report_ready_text: "PRazo prorrogado",
    },
  ],
  unsupported_rows: {
    total: 1,
    rows: [
      {
        row: { pasta: "72-2026", row_number: 10 },
        tema: "Implantação de Loja Virtual",
        demanda: "011547/2026",
        razao_social: "CASA NOSSA",
        especialista: "Christian Albuquerque Alonso",
        kick_off: "21/04/2026",
        link: "https://out-of-scope.example/",
        report_ready_text: "Prazo prorrogado",
        cause: "Tema is unsupported",
        explicacao: "Ainda não existe um Master aprovado para este Tema.",
      },
    ],
  },
}

const runningFixture: RunResponse = {
  run_id: "run-24",
  sheet_id: fixture.sheet_id,
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

const batchFixture: BatchResponse = {
  batch_id: "batch-29",
  sheet_id: fixture.sheet_id,
  runs: [
    runningFixture,
    {
      ...runningFixture,
      run_id: "run-29-queued",
      engagement: {
        row_number: 5,
        pasta: "40-2026",
        razao_social: "OUTRA EMPRESA LTDA",
      },
      outcome: "queued",
      current_stage: null,
      stages: runningFixture.stages.map((stage) => ({
        ...stage,
        state: "pending",
      })),
      stage_history: [],
      page_count: null,
    },
  ],
}

describe("control sheet upload", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/enviar")
    vi.stubGlobal("fetch", vi.fn())
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("opens the most recent retained sheet directly when it is the only one", async () => {
    window.history.replaceState({}, "", "/")
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            sheet_id: fixture.sheet_id,
            filename: fixture.filename,
            uploaded_at: "2026-07-30T18:00:00+00:00",
            ready_count: 2,
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    await screen.findByText("Pronto para gerar")
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/control-sheets")
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `/api/control-sheet/${fixture.sheet_id}`
    )
    expect(
      screen.queryByTestId("control-sheet-dropzone")
    ).not.toBeInTheDocument()
  })

  it("shows the retained sheet at step 1 instead of demanding a re-upload", async () => {
    window.history.replaceState({}, "", "/")
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            sheet_id: fixture.sheet_id,
            filename: fixture.filename,
            uploaded_at: "2026-07-30T18:00:00+00:00",
            ready_count: 2,
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    await screen.findByRole("checkbox", {
      name: /DENISE BARROS DE ALMEIDA.*linha 2/,
    })
    expect(
      screen.queryByTestId("control-sheet-dropzone")
    ).not.toBeInTheDocument()
  })

  it("keeps the chosen work when the sidebar switches steps and back", async () => {
    window.history.replaceState({}, "", "/")
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            sheet_id: fixture.sheet_id,
            filename: fixture.filename,
            uploaded_at: "2026-07-30T18:00:00+00:00",
            ready_count: 2,
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    const denise = /DENISE BARROS DE ALMEIDA.*linha 2/
    fireEvent.click(await screen.findByRole("checkbox", { name: denise }))
    expect(screen.getByRole("checkbox", { name: denise })).toBeChecked()

    expect(
      screen.getByRole("link", { name: "Trabalhos" })
    ).toHaveAccessibleDescription("2 trabalhos prontos para gerar")

    fireEvent.click(screen.getByRole("link", { name: "Em conferência" }))
    expect(
      screen.getByRole("heading", { name: "Nenhum relatório em conferência" })
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/conferir")

    fireEvent.click(screen.getByRole("link", { name: "Planilha" }))
    expect(
      await screen.findByTestId("control-sheet-dropzone")
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/")

    fireEvent.click(screen.getByRole("link", { name: "Trabalhos" }))
    expect(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*linha 2/,
      })
    ).toBeChecked()
    expect(window.location.pathname).toBe("/escolher")
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it("falls through to the drop area at step 1 when there is no retained sheet", async () => {
    window.history.replaceState({}, "", "/")
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, []))

    render(<App />)

    expect(
      await screen.findByTestId("control-sheet-dropzone")
    ).toBeInTheDocument()
  })

  it("offers retained sheet choices with upload dates and ready counts", async () => {
    window.history.replaceState({}, "", "/")
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse(200, [
          {
            sheet_id: "sheet-july",
            filename: "controle julho.xlsx",
            uploaded_at: "2026-07-30T18:00:00-03:00",
            ready_count: 2,
          },
          {
            sheet_id: "sheet-june",
            filename: "controle junho.xlsx",
            uploaded_at: "2026-06-30T18:00:00-03:00",
            ready_count: 1,
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    await screen.findByText("Escolha uma planilha")
    expect(screen.getByText("controle julho.xlsx")).toBeInTheDocument()
    expect(screen.getByText("controle junho.xlsx")).toBeInTheDocument()
    expect(screen.getByText(/2 trabalhos prontos/)).toBeInTheDocument()
    expect(screen.getByText(/30\/07\/2026/)).toBeInTheDocument()
    expect(
      screen.getByText(/planilhas ficam no servidor por sete dias/i)
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "Enviar nova planilha" })
    ).toHaveAttribute("href", "/enviar")
    expect(
      screen.queryByText(/computador por sete dias/i)
    ).not.toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", { name: "Usar controle julho.xlsx" })
    )
    await screen.findByText("Pronto para gerar")
    expect(fetch).toHaveBeenLastCalledWith("/api/control-sheet/sheet-july")
  })

  it("uploads via the file dialog and renders the Demandas table", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    const input = await screen.findByLabelText("Arquivo de planilha")
    fireEvent.change(input, { target: { files: [makeFile()] } })

    await screen.findByText("Pronto para gerar")

    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe("/api/control-sheet")
    expect(init?.method).toBe("POST")
    const formData = init?.body as FormData
    expect(formData.get("file")).toBeInstanceOf(File)

    expect(screen.getByText("Não dá para gerar")).toBeInTheDocument()
    expect(screen.getByText("Ainda não suportado")).toBeInTheDocument()
  })

  it("uploads via drag-and-drop and renders the Demandas table", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    const dropzone = await screen.findByTestId("control-sheet-dropzone")
    fireEvent.drop(dropzone, {
      dataTransfer: { files: [makeFile()] },
    })

    await screen.findByText("Pronto para gerar")
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it("shows a visible reading state while the workbook is parsed", async () => {
    let resolveFetch!: (value: Response) => void
    vi.mocked(fetch).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFetch = resolve
      })
    )

    render(<App />)

    const input = await screen.findByLabelText("Arquivo de planilha")
    fireEvent.change(input, { target: { files: [makeFile()] } })

    const status = await screen.findByRole("status")
    expect(status).toHaveTextContent(/lendo a planilha/i)
    expect(screen.getByTestId("control-sheet-dropzone")).toHaveAttribute(
      "aria-busy",
      "true"
    )

    resolveFetch(jsonResponse(200, fixture))
    await screen.findByText("Pronto para gerar")
  })

  it("shows every Engagement field on its row", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })

    await screen.findByText("Pronto para gerar")

    expect(screen.getByText("DENISE BARROS DE ALMEIDA")).toBeInTheDocument()
    expect(screen.getByText("https://denise.example/")).toBeInTheDocument()
    expect(screen.getByText("011616/2026")).toBeInTheDocument()
    expect(
      screen.getAllByText("Bruno Henrique Santana Leal").length
    ).toBeGreaterThan(0)
    expect(screen.getByText("15/04/2026")).toBeInTheDocument()
    expect(screen.getAllByText("40-2026").length).toBeGreaterThan(0)
    expect(screen.getByText("Link do site")).toBeInTheDocument()
    expect(screen.getByText("Início")).toBeInTheDocument()
    expect(screen.getAllByText("Prazo prorrogado")).toHaveLength(2)
    expect(screen.getByText("ok enviado")).toBeInTheDocument()
    expect(screen.queryByText("Capture Origin")).not.toBeInTheDocument()
    expect(screen.queryByText("Kick off")).not.toBeInTheDocument()
  })

  it("filters the table across row classes and can restore every Demanda", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByRole("heading", { name: "Demandas da planilha" })

    fireEvent.change(screen.getByLabelText("Filtrar Demandas"), {
      target: { value: "implantacao" },
    })

    expect(screen.getByText("CASA NOSSA")).toBeInTheDocument()
    expect(
      screen.queryByText("Implantação de Loja Virtual")
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("DENISE BARROS DE ALMEIDA")
    ).not.toBeInTheDocument()
    expect(screen.getByText("1–1 de 1 Demandas")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /Limpar/ }))

    expect(screen.getByText("DENISE BARROS DE ALMEIDA")).toBeInTheDocument()
    expect(screen.getByText("1–4 de 4 Demandas")).toBeInTheDocument()
    expect(
      screen.getByRole("combobox", { name: "Filtrar por situação" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("combobox", {
        name: "Filtrar por Relatório pronto?",
      })
    ).toBeInTheDocument()
  })

  it("derives the Relatório pronto filter from distinct sheet values", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByRole("heading", { name: "Demandas da planilha" })

    const reportFilter = screen.getByRole("combobox", {
      name: "Filtrar por Relatório pronto?",
    })
    const statusFilter = screen.getByRole("combobox", {
      name: "Filtrar por situação",
    })
    expect(screen.getByLabelText("Filtrar Demandas")).toHaveClass("rounded-sm")
    expect(reportFilter).toHaveClass("rounded-sm")
    expect(statusFilter).toHaveClass("rounded-sm")

    fireEvent.click(reportFilter)
    const postponedOptions = await screen.findAllByRole("option", {
      name: /prazo prorrogado/i,
    })
    expect(postponedOptions).toHaveLength(1)
    expect(
      screen.getByRole("option", {
        name: "ok enviado",
      })
    ).toBeInTheDocument()
    expect(
      postponedOptions[0].closest('[data-slot="select-content"]')
    ).toHaveClass("rounded-sm")

    expect(
      screen.queryByRole("option", {
        name: "preenchido",
      })
    ).not.toBeInTheDocument()
  })

  it("selects several Engagements independently", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")

    const generateButton = screen.getByRole("button", {
      name: "Selecione um trabalho",
    })
    expect(generateButton).toBeDisabled()
    expect(
      screen.getByRole("heading", { name: "Demandas da planilha" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("columnheader", { name: /Pasta/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("columnheader", { name: /Situação/ })
    ).toBeInTheDocument()

    const firstCheckbox = screen.getByRole("checkbox", {
      name: /DENISE BARROS DE ALMEIDA.*linha 2/,
    })
    expect(
      generateButton.compareDocumentPosition(firstCheckbox) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    fireEvent.click(firstCheckbox)

    const generateOne = await screen.findByRole("button", {
      name: "Gerar relatório",
    })
    expect(generateOne).toBeEnabled()

    const secondCheckbox = screen.getByRole("checkbox", {
      name: /OUTRA EMPRESA LTDA.*linha 5/,
    })
    fireEvent.click(secondCheckbox)

    expect(
      screen.getByRole("checkbox", {
        name: /OUTRA EMPRESA LTDA.*linha 5/,
      })
    ).toBeChecked()
    expect(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*linha 2/,
      })
    ).toBeChecked()
    expect(
      screen.getByRole("button", { name: "Gerar 2 relatórios" })
    ).toBeEnabled()

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /OUTRA EMPRESA LTDA.*linha 5/,
      })
    )

    expect(
      await screen.findByRole("button", { name: "Gerar relatório" })
    ).toBeEnabled()
  })

  it("selects two engagements sharing a Pasta independently", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")

    const rowOne = screen.getByRole("checkbox", {
      name: /DENISE BARROS DE ALMEIDA.*pasta 40-2026.*linha 2/,
    })
    const rowTwo = screen.getByRole("checkbox", {
      name: /OUTRA EMPRESA LTDA.*pasta 40-2026.*linha 5/,
    })

    fireEvent.click(rowOne)

    expect(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*pasta 40-2026.*linha 2/,
      })
    ).toBeChecked()
    expect(rowTwo).not.toBeChecked()
    expect(
      screen.getByRole("button", { name: "Gerar relatório" })
    ).toBeEnabled()
  })

  it("starts the selected Engagement and shows real resumable progress", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(200, fixture))
      .mockResolvedValueOnce(jsonResponse(202, runningFixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*linha 2/,
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "Gerar relatório" }))

    await screen.findByText("Gerando agora")
    expect(
      screen.getByText("40-2026 · DENISE BARROS DE ALMEIDA")
    ).toBeInTheDocument()
    expect(screen.getByText("Lista de Páginas: 7 itens")).toBeInTheDocument()
    expect(
      screen.getByText("Capturando páginas, Cabeçalho e Rodapé")
    ).toBeInTheDocument()
    expect(
      screen.getByText(/fechar esta aba e voltar depois/i)
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/relatorios/run-24")
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          sheet_id: fixture.sheet_id,
          row_number: 2,
        }),
      })
    )
  })

  it("starts a selected batch and shows the running and queued Engagements", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(200, fixture))
      .mockResolvedValueOnce(jsonResponse(202, batchFixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*linha 2/,
      })
    )
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /OUTRA EMPRESA LTDA.*linha 5/,
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "Gerar 2 relatórios" }))

    await screen.findByRole("heading", { name: "Lote em andamento" })
    expect(screen.getByText("Gerando agora")).toBeInTheDocument()
    expect(screen.getByText("Na fila")).toBeInTheDocument()
    // The work table stays mounted (hidden) to keep its selection, so it
    // also lists this company; only the visible batch view counts here.
    expect(
      screen.getByText("OUTRA EMPRESA LTDA", { ignore: "[hidden] *" })
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe("/lotes/batch-29")
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/batches",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          sheet_id: fixture.sheet_id,
          row_numbers: [2, 5],
        }),
      })
    )
  })

  it("returns to the drop area when the working sheet expires before a run starts", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(200, fixture))
      .mockResolvedValueOnce(
        jsonResponse(404, {
          detail:
            "Esta planilha expirou ou não é conhecida. Envie-a novamente.",
        })
      )

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*linha 2/,
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "Gerar relatório" }))

    expect(
      await screen.findByTestId("control-sheet-dropzone")
    ).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent(/expirou/i)
    expect(window.location.pathname).toBe("/enviar")
  })

  it("shows original Stop Condition fields and moves its explanation to a tooltip", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Não dá para gerar")

    const stopRow = screen
      .getByText("EMPRESA COM DADO PENDENTE LTDA")
      .closest("tr") as HTMLElement
    expect(within(stopRow).queryByRole("checkbox")).not.toBeInTheDocument()
    expect(within(stopRow).getByText("011800/2026")).toBeInTheDocument()
    expect(within(stopRow).getByText("25/04/2026")).toBeInTheDocument()
    expect(
      within(stopRow).getByText("https://pendente.example/")
    ).toBeInTheDocument()
    expect(
      within(stopRow).queryByText("A coluna nº da pasta está vazia.")
    ).not.toBeInTheDocument()
    expect(
      within(stopRow).queryByText(/Pasta is absent/)
    ).not.toBeInTheDocument()
    expect(within(stopRow).getByText("Bloqueada")).toBeInTheDocument()
    const explanation = within(stopRow).getByRole("button", {
      name: "Por que a linha 8 está bloqueada?",
    })
    fireEvent.focus(explanation)
    expect(
      await screen.findByText("A coluna nº da pasta está vazia.")
    ).toBeInTheDocument()
    expect(
      screen.getByText("Preencha o número da pasta, como 115-2026.")
    ).toBeInTheDocument()
    expect(stopRow).toHaveAttribute("data-status", "blocked")
    expect(stopRow).toHaveClass("bg-destructive/5")
  })

  it("lists unsupported rows distinctly and without a checkbox", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Ainda não suportado")
    const unsupportedRow = screen
      .getByText("CASA NOSSA")
      .closest("tr") as HTMLElement

    expect(
      within(unsupportedRow).getByText(/Prazo prorrogado/)
    ).toBeInTheDocument()
    expect(within(unsupportedRow).getByText("011547/2026")).toBeInTheDocument()
    expect(
      within(unsupportedRow).getByText("Christian Albuquerque Alonso")
    ).toBeInTheDocument()
    expect(
      within(unsupportedRow).getByText("https://out-of-scope.example/")
    ).toBeInTheDocument()
    expect(
      within(unsupportedRow).queryByText("Implantação de Loja Virtual")
    ).not.toBeInTheDocument()
    expect(
      within(unsupportedRow).getByText("Tema sem suporte")
    ).toBeInTheDocument()
    const explanation = within(unsupportedRow).getByRole("button", {
      name: "Por que a linha 10 ainda não é suportada?",
    })
    fireEvent.focus(explanation)
    expect(
      await screen.findByText("Implantação de Loja Virtual")
    ).toBeInTheDocument()
    expect(
      screen.getByText("Ainda não existe um Master aprovado para este Tema.")
    ).toBeInTheDocument()
    expect(
      within(unsupportedRow).queryByRole("checkbox")
    ).not.toBeInTheDocument()
    expect(unsupportedRow).toHaveAttribute("data-status", "unsupported")
    expect(unsupportedRow).toHaveClass("bg-amber-50/70")
  })

  it("says so instead of an empty list when nothing is generatable", async () => {
    const zeroEngagements: ControlSheetResponse = {
      ...fixture,
      engagements: [],
    }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, zeroEngagements))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })

    await screen.findByRole("heading", { name: "Demandas da planilha" })
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
    expect(screen.getByText("Não dá para gerar")).toBeInTheDocument()
    expect(screen.getByText("Ainda não suportado")).toBeInTheDocument()
    expect(screen.getByText("1–2 de 2 Demandas")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Selecione um trabalho" })
    ).toBeDisabled()
  })

  it("returns to the drop area with the 422 detail and accepts a corrected upload without a reload", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(422, {
        detail: "A planilha não tem a aba “LV e Site”.",
      })
    )

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile("errado.xlsx")] },
    })

    await screen.findByText("A planilha não tem a aba “LV e Site”.")
    expect(screen.getByTestId("control-sheet-dropzone")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Escolher planilha" })
    ).toBeEnabled()

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })

    await screen.findByText("Pronto para gerar")
    expect(
      screen.queryByText("A planilha não tem a aba “LV e Site”.")
    ).not.toBeInTheDocument()
  })

  it("replaces the previous results entirely on a second successful upload", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /DENISE BARROS DE ALMEIDA.*linha 2/,
      })
    )
    expect(
      screen.getByRole("button", { name: "Gerar relatório" })
    ).toBeInTheDocument()

    const secondFixture: ControlSheetResponse = {
      ...fixture,
      sheet_id: "second-sheet-id",
      engagements: [fixture.engagements[0]],
      unsupported_rows: {
        total: 0,
        rows: [],
      },
    }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, secondFixture))
    fireEvent.change(screen.getByLabelText("Enviar outra planilha"), {
      target: { files: [makeFile("segunda.xlsx")] },
    })

    await waitFor(() => {
      expect(screen.getAllByRole("checkbox")).toHaveLength(1)
    })
    expect(
      screen.getByRole("button", { name: "Selecione um trabalho" })
    ).toBeDisabled()
  })

  it("shows the reading state while a replacement workbook is parsed", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")

    let release: (value: Response) => void = () => {}
    vi.mocked(fetch).mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        release = resolve
      })
    )
    fireEvent.change(screen.getByLabelText("Enviar outra planilha"), {
      target: { files: [makeFile("segunda.xlsx")] },
    })

    await screen.findByText("Lendo a planilha, isso pode levar um instante…")
    expect(
      screen.getByRole("button", { name: "Enviar outra planilha" })
    ).toBeDisabled()

    release(jsonResponse(200, fixture))
    await waitFor(() => {
      expect(
        screen.queryByText("Lendo a planilha, isso pode levar um instante…")
      ).not.toBeInTheDocument()
    })
  })

  it("keeps the loaded rows when a replacement upload is rejected", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")

    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(422, {
        detail: "Este arquivo não é uma planilha .xlsx que possamos ler.",
      })
    )
    fireEvent.change(screen.getByLabelText("Enviar outra planilha"), {
      target: { files: [makeFile("nota.txt")] },
    })

    await screen.findByText(
      "Este arquivo não é uma planilha .xlsx que possamos ler."
    )
    expect(screen.getByText("DENISE BARROS DE ALMEIDA")).toBeInTheDocument()
    expect(screen.getAllByRole("checkbox")).toHaveLength(2)
  })
})
