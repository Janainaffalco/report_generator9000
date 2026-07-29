import "@testing-library/jest-dom/vitest"

import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { App } from "@/App"

describe("upload shell", () => {
  it("presents the approved first-stage structure and honest delivery copy", () => {
    render(<App />)

    expect(screen.getByText("Relatórios")).toBeInTheDocument()
    expect(
      screen.getByText("Relatório Técnico Final · SEBRAETEC"),
    ).toBeInTheDocument()
    expect(screen.getByText("sem cadastro · sem senha")).toBeInTheDocument()
    expect(screen.getByText("1 · Enviar planilha")).toBeInTheDocument()
    expect(screen.getByText("2 · Escolher o trabalho")).toBeInTheDocument()
    expect(screen.getByText("3 · Conferir o relatório")).toBeInTheDocument()
    expect(screen.getByText("4 · Baixar")).toBeInTheDocument()
    expect(screen.getByText(".xlsx")).toBeInTheDocument()
    expect(screen.getByText(/aba “LV e Site”/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Escolher planilha" })).toBeEnabled()
    expect(screen.getByText("Nada para configurar")).toBeInTheDocument()
    expect(
      screen.getByText("Só os trabalhos que dão para fazer"),
    ).toBeInTheDocument()
    expect(screen.getByText("Documento Word no fim")).toBeInTheDocument()
    expect(screen.queryByText(/\.pdf/i)).not.toBeInTheDocument()
    expect(screen.getByText(/mantidos no servidor por sete dias/i)).toBeInTheDocument()
    expect(
      screen.getByText(/nenhum dado do cliente é enviado a uma conta de terceiros/i),
    ).toBeInTheDocument()
  })
})
