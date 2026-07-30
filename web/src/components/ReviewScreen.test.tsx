import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ReviewScreen } from "@/components/ReviewScreen"
import type { RunResponse } from "@/lib/runs"

function response(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response
}

const run: RunResponse = {
  run_id: "run-1",
  sheet_id: "sheet-1",
  engagement: { row_number: 2, pasta: "40-2026", razao_social: "CLIENTE" },
  outcome: "finished",
  current_stage: null,
  stages: [],
  stage_history: [],
  page_count: 3,
  status: "draft",
  filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.docx",
  reason: null,
  download_url: "/api/runs/run-1/download",
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("ReviewScreen", () => {
  it("distinguishes GATED, TOOL_BLOCKED and UNDECLARED Pendências", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "draft",
          preview_page_count: 5,
          page_count: 3,
          filename: run.filename,
          download_url: run.download_url,
          pendencias: [
            {
              classification: "GATED",
              classification_label: "NÃO FORNECIDO",
              classification_explanation:
                "Normal e esperado: nenhuma automação consegue obter este conteúdo sozinha.",
              name: "documento cnpj",
              required_action: "Fornecer documento cnpj no valores.json",
              page: "documento",
            },
            {
              classification: "TOOL_BLOCKED",
              classification_label: "FALHA NA AUTOMAÇÃO",
              classification_explanation:
                "Defeito da automação: a captura falhou e gerar de novo pode resolver.",
              name: "captura da PÁGINA HOME",
              required_action: "Gerar novamente",
              page: "PÁGINA HOME",
            },
            {
              classification: "UNDECLARED",
              classification_label: "NÃO DECLARADO",
              classification_explanation:
                "O site não declara essa informação — é uma característica do site, não uma falha da geração.",
              name: "paleta de cores",
              required_action: "Revisar a paleta no Word",
              page: "documento",
            },
          ],
          checks: [],
        }),
      ),
    )

    render(<ReviewScreen run={run} />)

    await screen.findByText("documento cnpj")
    const gated = screen.getByText("documento cnpj").closest("li")!
    const toolBlocked = screen
      .getByText("captura da PÁGINA HOME")
      .closest("li")!
    const undeclared = screen.getByText("paleta de cores").closest("li")!

    expect(within(gated).getByText("NÃO FORNECIDO")).toBeInTheDocument()
    expect(
      within(gated).getByText(/nenhuma automação consegue obter/i),
    ).toBeInTheDocument()
    expect(
      within(toolBlocked).getByText("FALHA NA AUTOMAÇÃO"),
    ).toBeInTheDocument()
    expect(
      within(toolBlocked).getByText(/gerar de novo pode resolver/i),
    ).toBeInTheDocument()
    expect(within(undeclared).getByText("NÃO DECLARADO")).toBeInTheDocument()
    expect(
      within(undeclared).getByText(/característica do site/i),
    ).toBeInTheDocument()

    // The three classes must never read as the same thing.
    const labels = [
      within(gated).getByText("NÃO FORNECIDO").textContent,
      within(toolBlocked).getByText("FALHA NA AUTOMAÇÃO").textContent,
      within(undeclared).getByText("NÃO DECLARADO").textContent,
    ]
    expect(new Set(labels).size).toBe(3)

    expect(
      screen.getByText(/podem ser resolvidas aqui na revisão ou/i),
    ).toBeInTheDocument()
  })

  it("states the report is ready for signature when there are no Pendências", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "complete",
          preview_page_count: 4,
          page_count: 2,
          filename: run.filename,
          download_url: run.download_url,
          pendencias: [],
          checks: [
            { label: "Nenhuma imagem de outro cliente no arquivo", passed: true },
          ],
        }),
      ),
    )

    render(<ReviewScreen run={run} />)

    expect(await screen.findByText("Pronto para assinatura")).toBeInTheDocument()
    expect(
      screen.getAllByText(/pronto para assinatura/i).length,
    ).toBeGreaterThanOrEqual(2)
  })

  it("reflects the actual gate results, and the page rail jumps the counter", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "complete",
          preview_page_count: 5,
          page_count: 3,
          filename: run.filename,
          download_url: run.download_url,
          pendencias: [],
          checks: [
            { label: "Os links apontam para o cliente certo", passed: true },
            { label: "Todo título de Bloco tem sua imagem", passed: false },
          ],
        }),
      ),
    )

    render(<ReviewScreen run={run} />)

    await screen.findByText("Os links apontam para o cliente certo")
    expect(
      screen.getByText("Todo título de Bloco tem sua imagem"),
    ).toBeInTheDocument()
    // The rail and the counter follow the document's own pages, never the
    // Lista de Páginas — the response deliberately disagrees on the two.
    expect(screen.getByText("Página 1 de 5")).toBeInTheDocument()
    expect(
      screen.getByText(/aproximada da paginação/i),
    ).toBeInTheDocument()

    const pageButtons = screen.getAllByRole("button")
    expect(pageButtons).toHaveLength(5)

    const framedImage = document.querySelector(".preview-frame img")
    expect(framedImage).toHaveAttribute("src", "/api/runs/run-1/previews/1")

    fireEvent.click(pageButtons[4])

    expect(screen.getByText("Página 5 de 5")).toBeInTheDocument()
    expect(pageButtons[4]).toHaveAttribute("aria-current", "page")
    expect(document.querySelector(".preview-frame img")).toHaveAttribute(
      "src",
      "/api/runs/run-1/previews/5",
    )
  })
})
