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
    },
    {
      row: { pasta: "40-2026", row_number: 5 },
      demanda: "011700/2026",
      razao_social: "OUTRA EMPRESA LTDA",
      especialista: "Ana Paula Ferreira",
      kick_off: "20/04/2026",
      capture_origin: "https://outra.example/",
      published_domain: null,
    },
  ],
  stop_conditions: [
    {
      row: { pasta: null, row_number: 8 },
      coluna: "nº da pasta",
      problema: "A coluna nº da pasta está vazia.",
      solucao: "Preencha o número da pasta, como 115-2026.",
      cause: "Pasta is absent",
    },
  ],
  skipped_rows: {
    total: 2,
    resumo: "2 linhas ficaram de fora",
    reasons: [
      {
        cause: "Tema is out of scope",
        titulo: "Tema fora do escopo",
        explicacao:
          "São linhas de Implantação de Loja Virtual. Ainda não existe um Master aprovado para esse Tema, então não há de onde gerar o relatório — a linha está correta, só não é deste pipeline.",
        total: 1,
        rows: [{ pasta: "72-2026", row_number: 10 }],
      },
      {
        cause: "already complete",
        titulo: "Relatório já marcado como pronto",
        explicacao:
          "A coluna “Relatório pronto?” já está preenchida, então a linha foi deixada de fora.",
        total: 1,
        rows: [{ pasta: "90-2026", row_number: 11 }],
      },
    ],
  },
}

describe("control sheet upload", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn())
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("uploads via the file dialog and renders the three groups", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    const input = screen.getByLabelText("Arquivo de planilha")
    fireEvent.change(input, { target: { files: [makeFile()] } })

    await screen.findByText("Pronto para gerar")

    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe("/api/control-sheet")
    expect(init?.method).toBe("POST")
    const formData = init?.body as FormData
    expect(formData.get("file")).toBeInstanceOf(File)

    expect(screen.getByText("Não dá para gerar")).toBeInTheDocument()
    expect(screen.getByText("Ficou de fora")).toBeInTheDocument()
  })

  it("uploads via drag-and-drop and renders the three groups", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)

    const dropzone = screen.getByTestId("control-sheet-dropzone")
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

    const input = screen.getByLabelText("Arquivo de planilha")
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
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })

    await screen.findByText("Pronto para gerar")

    expect(screen.getByText("DENISE BARROS DE ALMEIDA")).toBeInTheDocument()
    expect(screen.getByText("https://denise.example/")).toBeInTheDocument()
    expect(screen.getByText("011616/2026")).toBeInTheDocument()
    expect(screen.getByText("Bruno Henrique Santana Leal")).toBeInTheDocument()
    expect(screen.getByText("15/04/2026")).toBeInTheDocument()
    expect(screen.getAllByText("40-2026").length).toBeGreaterThan(0)
  })

  it("selects and deselects rows, updating the generate control's label", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Pronto para gerar")

    const generateButton = screen.getByRole("button", {
      name: "Selecione ao menos um trabalho",
    })
    expect(generateButton).toBeDisabled()

    const firstCheckbox = screen.getByRole("checkbox", {
      name: /DENISE BARROS DE ALMEIDA.*linha 2/,
    })
    fireEvent.click(firstCheckbox)

    const generateOne = await screen.findByRole("button", {
      name: "Gerar relatório",
    })
    expect(generateOne).toBeEnabled()

    const secondCheckbox = screen.getByRole("checkbox", {
      name: /OUTRA EMPRESA LTDA.*linha 5/,
    })
    fireEvent.click(secondCheckbox)

    const generateTwo = await screen.findByRole("button", {
      name: "Gerar 2 relatórios",
    })
    expect(generateTwo).toBeEnabled()

    fireEvent.click(firstCheckbox)
    fireEvent.click(secondCheckbox)

    expect(
      await screen.findByRole("button", {
        name: "Selecione ao menos um trabalho",
      })
    ).toBeDisabled()
  })

  it("selects two engagements sharing a Pasta independently", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
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

    expect(rowOne).toBeChecked()
    expect(rowTwo).not.toBeChecked()
    expect(
      screen.getByRole("button", { name: "Gerar relatório" })
    ).toBeEnabled()
  })

  it("shows Stop Condition rows with no checkbox, Portuguese copy and the original cause", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Não dá para gerar")

    const stopHeading = screen.getByText("Não dá para gerar")
    const stopSection = stopHeading.closest("section") as HTMLElement
    expect(within(stopSection).queryByRole("checkbox")).not.toBeInTheDocument()

    expect(
      within(stopSection).getByText("A coluna nº da pasta está vazia.")
    ).toBeInTheDocument()
    expect(
      within(stopSection).getByText(
        "Preencha o número da pasta, como 115-2026."
      )
    ).toBeInTheDocument()
    expect(within(stopSection).getByText(/Pasta is absent/)).toBeInTheDocument()
    expect(
      within(stopSection).getByText(/prefere parar a inventar um valor/i)
    ).toBeInTheDocument()
  })

  it("expands and collapses the Skipped Rows breakdown", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })
    await screen.findByText("Ficou de fora")

    expect(screen.getByText("2 linhas ficaram de fora")).toBeInTheDocument()
    expect(screen.queryByText("Tema fora do escopo")).not.toBeInTheDocument()

    fireEvent.click(screen.getByText("2 linhas ficaram de fora"))

    expect(await screen.findByText("Tema fora do escopo")).toBeInTheDocument()
    expect(
      screen.getByText("Relatório já marcado como pronto")
    ).toBeInTheDocument()

    fireEvent.click(screen.getByText("2 linhas ficaram de fora"))

    await waitFor(() =>
      expect(screen.queryByText("Tema fora do escopo")).not.toBeInTheDocument()
    )
  })

  it("says so instead of an empty list when nothing is generatable", async () => {
    const zeroEngagements: ControlSheetResponse = {
      ...fixture,
      engagements: [],
    }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, zeroEngagements))

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile()] },
    })

    await screen.findByText(
      "Nenhuma linha desta planilha está pronta para gerar."
    )
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
    expect(screen.getByText("Não dá para gerar")).toBeInTheDocument()
    expect(screen.getByText("Ficou de fora")).toBeInTheDocument()
  })

  it("returns to the drop area with the 422 detail and accepts a corrected upload without a reload", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(422, {
        detail: "A planilha não tem a aba “LV e Site”.",
      })
    )

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
      target: { files: [makeFile("errado.xlsx")] },
    })

    await screen.findByText("A planilha não tem a aba “LV e Site”.")
    expect(screen.getByTestId("control-sheet-dropzone")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Escolher planilha" })
    ).toBeEnabled()

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
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
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
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
      skipped_rows: {
        total: 0,
        resumo: "0 linhas ficaram de fora",
        reasons: [],
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
      screen.getByRole("button", { name: "Selecione ao menos um trabalho" })
    ).toBeDisabled()
  })

  it("shows the reading state while a replacement workbook is parsed", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, fixture))

    render(<App />)
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
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
    fireEvent.change(screen.getByLabelText("Arquivo de planilha"), {
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
