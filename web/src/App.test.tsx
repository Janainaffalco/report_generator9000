import "@testing-library/jest-dom/vitest"

import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { App, currentStage } from "@/App"

describe("upload shell", () => {
  afterEach(() => {
    cleanup()
  })

  it("presents the approved first-stage structure and honest delivery copy", () => {
    window.history.replaceState({}, "", "/enviar")
    render(<App />)

    expect(
      screen.getByText("Gerador de Relatórios SEBRAETEC")
    ).toBeInTheDocument()
    expect(
      screen.queryByText("sem cadastro · sem senha")
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "1·Enviar planilha" })
    ).toHaveAttribute("aria-current", "step")
    expect(
      screen.getByRole("link", { name: "2·Escolher o trabalho" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "3·Conferir o relatório" })
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "4·Baixar" })).toBeInTheDocument()
    expect(screen.getByText(".xlsx")).toBeInTheDocument()
    expect(screen.getByText(/aba “LV e Site”/)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Escolher planilha" })
    ).toBeEnabled()
    expect(
      screen.getByText(
        "Extração automática com consistência de screenshots das páginas"
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText("Extração automática de paleta de cores do site")
    ).toBeInTheDocument()
    expect(screen.getByText("Documento Word no fim")).toBeInTheDocument()
    expect(screen.queryByText("Comece aqui")).not.toBeInTheDocument()
    expect(screen.getByText("Beta")).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /suporte via whatsapp/i })
    ).toHaveAttribute("href", "https://wa.me/5511911926036")
    expect(screen.queryByText(/\.pdf/i)).not.toBeInTheDocument()
    expect(
      screen.getByText(/mantidos no servidor por sete dias/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /nenhum dado do cliente é enviado a uma conta de terceiros/i
      )
    ).toBeInTheDocument()
  })

  it("points the first stepper step at the root path, not the drop-area route", () => {
    window.history.replaceState({}, "", "/enviar")
    render(<App />)

    expect(
      screen.getByRole("link", { name: "1·Enviar planilha" })
    ).toHaveAttribute("href", "/")
  })
})

describe("currentStage", () => {
  it("resolves both the root path and the drop-area route to stage 1", () => {
    expect(currentStage("/")).toBe(1)
    expect(currentStage("/enviar")).toBe(1)
  })

  it("resolves every other stage's own path to its own number", () => {
    const cases: Array<[string, number]> = [
      ["/escolher", 2],
      ["/conferir", 3],
      ["/baixar", 4],
    ]

    for (const [path, expected] of cases) {
      expect(currentStage(path)).toBe(expected)
    }
  })

  it("falls back to stage 1 for an unrecognized path", () => {
    expect(currentStage("/algo-desconhecido")).toBe(1)
  })
})
