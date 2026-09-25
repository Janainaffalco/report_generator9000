import "@testing-library/jest-dom/vitest"

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react"
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
  pdf_download_url: "/api/runs/run-1/download/pdf",
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("ReviewScreen", () => {
  it("distinguishes GATED, TOOL_BLOCKED, UNDECLARED and INCONCLUSIVO Pendências", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "draft",
          page_count: 5,
          filename: run.filename,
          download_url: run.download_url,
          pdf_filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.pdf",
          pdf_download_url: run.pdf_download_url,
          pendencias: [
            {
              classification: "GATED",
              classification_label: "NÃO FORNECIDO",
              classification_explanation:
                "Normal e esperado: nenhuma automação consegue obter este conteúdo sozinha.",
              name: "documento cnpj",
              required_action: "Fornecer documento cnpj no valores.json",
              page: "documento",
              preview_page: 4,
            },
            {
              classification: "TOOL_BLOCKED",
              classification_label: "FALHA NA AUTOMAÇÃO",
              classification_explanation:
                "Defeito da automação: a captura falhou e gerar de novo pode resolver.",
              name: "captura da PÁGINA HOME",
              required_action: "Gerar novamente",
              page: "PÁGINA HOME",
              preview_page: null,
            },
            {
              classification: "UNDECLARED",
              classification_label: "NÃO DECLARADO",
              classification_explanation:
                "O site não declara essa informação — é uma característica do site, não uma falha da geração.",
              name: "paleta de cores",
              required_action: "Revisar a paleta no Word",
              page: "documento",
              preview_page: null,
            },
            {
              classification: "INCONCLUSIVO",
              classification_label: "INCONCLUSIVO",
              classification_explanation:
                "A evidência pública do site não permite concluir — confirme na loja e ajuste no Word; não é uma falha da geração.",
              name: "caminho de compra",
              required_action:
                "Confirmar na loja pública como o visitante conclui a compra e revisar no Word",
              page: "FUNCIONALIDADES DA LOJA",
              preview_page: null,
            },
          ],
          checks: [],
        })
      )
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
      within(gated).getByText(/nenhuma automação consegue obter/i)
    ).toBeInTheDocument()
    expect(
      within(toolBlocked).getByText("FALHA NA AUTOMAÇÃO")
    ).toBeInTheDocument()
    expect(
      within(toolBlocked).getByText(/gerar de novo pode resolver/i)
    ).toBeInTheDocument()
    expect(within(undeclared).getByText("NÃO DECLARADO")).toBeInTheDocument()
    expect(
      within(undeclared).getByText(/característica do site/i)
    ).toBeInTheDocument()

    const inconclusive = screen.getByText("caminho de compra").closest("li")!
    expect(
      within(inconclusive).getByText("INCONCLUSIVO")
    ).toBeInTheDocument()
    expect(
      within(inconclusive).getByText(/não permite concluir/i)
    ).toBeInTheDocument()

    // The classes must never read as the same thing.
    const labels = [
      within(gated).getByText("NÃO FORNECIDO").textContent,
      within(toolBlocked).getByText("FALHA NA AUTOMAÇÃO").textContent,
      within(undeclared).getByText("NÃO DECLARADO").textContent,
      within(inconclusive).getByText("INCONCLUSIVO").textContent,
    ]
    expect(new Set(labels).size).toBe(4)

    expect(
      screen.getByText(/podem ser resolvidas agora ou depois, direto no Word/i)
    ).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole("button", {
        name: /página 4 · clique para ver no documento/i,
      })
    )
    expect(screen.getByText("Página 4 de 5")).toBeInTheDocument()
  })

  it("states the report is ready for signature when there are no Pendências", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "complete",
          page_count: 4,
          filename: run.filename,
          download_url: run.download_url,
          pdf_filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.pdf",
          pdf_download_url: run.pdf_download_url,
          pendencias: [],
          checks: [
            {
              label: "Nenhuma imagem de outro cliente no arquivo",
              passed: true,
            },
          ],
        })
      )
    )

    render(<ReviewScreen run={run} />)

    expect(await screen.findByText("Completo")).toBeInTheDocument()
    expect(
      screen.getAllByText(/pronto para assinatura/i).length
    ).toBeGreaterThanOrEqual(2)
  })

  it("reflects the actual gate results, and the page rail jumps the counter", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "complete",
          page_count: 5,
          filename: run.filename,
          download_url: run.download_url,
          pdf_filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.pdf",
          pdf_download_url: run.pdf_download_url,
          pendencias: [],
          checks: [
            { label: "Os links apontam para o cliente certo", passed: true },
            { label: "Todo título de Bloco tem sua imagem", passed: false },
          ],
        })
      )
    )

    render(<ReviewScreen run={run} />)

    await screen.findByText("Os links apontam para o cliente certo")
    expect(
      screen.getByText("Todo título de Bloco tem sua imagem")
    ).toBeInTheDocument()
    // The report resource's page_count is the document's own count.
    expect(screen.getByText("Página 1 de 5")).toBeInTheDocument()
    expect(screen.queryByText(/aproximada da paginação/i)).not.toBeInTheDocument()
    expect(
      screen.getByText(/Páginas do PDF gerado a partir deste \.docx/i)
    ).toBeInTheDocument()
    expect(screen.getByText("5 páginas")).toBeInTheDocument()

    const pageButtons = screen.getAllByRole("button")
    expect(pageButtons).toHaveLength(5)

    const framedImage = document.querySelector(".preview-frame img")
    expect(framedImage).toHaveAttribute("src", "/api/runs/run-1/previews/1")

    fireEvent.click(pageButtons[4])

    expect(screen.getByText("Página 5 de 5")).toBeInTheDocument()
    expect(pageButtons[4]).toHaveAttribute("aria-current", "page")
    expect(document.querySelector(".preview-frame img")).toHaveAttribute(
      "src",
      "/api/runs/run-1/previews/5"
    )
  })

  it("maps several attachments to Pendências before starting the rerun", async () => {
    const onRegenerated = vi.fn()
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          response({
            run_id: "run-1",
            status: "draft",
            page_count: 1,
            filename: run.filename,
            download_url: run.download_url,
            pdf_filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.pdf",
            pdf_download_url: run.pdf_download_url,
            pendencias: [
              {
                classification: "GATED",
                classification_label: "NÃO FORNECIDO",
                classification_explanation: "Normal e esperado.",
                name: "paleta de cores",
                required_action: "Anexar paleta.png",
                page: "documento",
                preview_page: null,
                attachment_filename: "paleta.png",
              },
              {
                classification: "GATED",
                classification_label: "NÃO FORNECIDO",
                classification_explanation: "Normal e esperado.",
                name: "painel WordPress",
                required_action: "Anexar painel.png",
                page: "documento",
                preview_page: null,
                attachment_filename: "painel.png",
              },
            ],
            checks: [],
          })
        )
        .mockResolvedValueOnce(
          response({ ...run, run_id: "rerun-2", outcome: "running" })
        )
    )
    render(<ReviewScreen run={run} onRegenerated={onRegenerated} />)
    const input = await screen.findByLabelText("Anexar itens disponíveis")
    fireEvent.change(input, {
      target: {
        files: [
          new File(["palette"], "paleta.png", { type: "image/png" }),
          new File(["panel"], "painel.png", { type: "image/png" }),
        ],
      },
    })
    expect(screen.getByText(/paleta.png → paleta de cores/)).toBeInTheDocument()
    expect(
      screen.getByText(/painel.png → painel WordPress/)
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole("button", { name: "Anexar e gerar novamente" })
    )
    await vi.waitFor(() => expect(onRegenerated).toHaveBeenCalled())
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/runs/run-1/attachments",
      expect.objectContaining({ method: "POST" })
    )
  })

  it("offers both format downloads with correct hrefs and thumbnails matching the page count", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "complete",
          page_count: 3,
          filename: run.filename,
          download_url: run.download_url,
          pdf_filename: "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.pdf",
          pdf_download_url: "/api/runs/run-1/download/pdf",
          pendencias: [],
          checks: [],
        })
      )
    )

    render(<ReviewScreen run={run} />)

    const docxLink = await screen.findByRole("link", { name: "Baixar .docx" })
    expect(docxLink).toHaveAttribute("href", run.download_url)

    const pdfLink = screen.getByRole("link", { name: "Baixar .pdf" })
    expect(pdfLink).toHaveAttribute("href", "/api/runs/run-1/download/pdf")
    expect(pdfLink).toHaveAttribute(
      "download",
      "RELATÓRIO TÉCNICO FINAL - 40-2026_CLIENTE.pdf"
    )

    expect(screen.getByText("3 páginas")).toBeInTheDocument()
    const thumbnails = screen.getAllByRole("img", { name: /^Página \d+$/ })
    expect(thumbnails).toHaveLength(3)
  })

  it("hides the PDF download when the run has no rendered PDF", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          run_id: "run-1",
          status: "complete",
          page_count: 1,
          filename: run.filename,
          download_url: run.download_url,
          pdf_filename: null,
          pdf_download_url: null,
          pendencias: [],
          checks: [],
        })
      )
    )

    render(<ReviewScreen run={run} />)

    await screen.findByRole("link", { name: "Baixar .docx" })
    expect(
      screen.queryByRole("link", { name: "Baixar .pdf" })
    ).not.toBeInTheDocument()
    expect(screen.getByText("1 página")).toBeInTheDocument()
  })
})
