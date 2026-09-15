import "@testing-library/jest-dom/vitest"

import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"

vi.mock("@/lib/session", () => ({
  getSession: vi.fn(async () => true),
  login: vi.fn(),
  logout: vi.fn(),
}))

describe("upload shell", () => {
  afterEach(() => {
    cleanup()
  })

  it("presents the approved first-stage structure and honest delivery copy", async () => {
    window.history.replaceState({}, "", "/enviar")
    render(<App />)

    expect(
      await screen.findByText("Gerador de Relatórios SEBRAETEC")
    ).toBeInTheDocument()
    expect(
      screen.queryByText("sem cadastro · sem senha")
    ).not.toBeInTheDocument()
    const nav = within(
      screen.getByRole("navigation", { name: "Navegação principal" })
    )
    expect(nav.getByText("Gerar")).toBeInTheDocument()
    expect(nav.getByText("Arquivo")).toBeInTheDocument()
    expect(nav.getByRole("link", { name: "Planilha" })).toHaveAttribute(
      "aria-current",
      "page"
    )
    expect(nav.getByRole("link", { name: "Trabalhos" })).toBeInTheDocument()
    expect(
      nav.getByRole("link", { name: "Em conferência" })
    ).toBeInTheDocument()
    expect(nav.getByRole("link", { name: "Relatórios" })).toHaveAttribute(
      "href",
      "/relatorios"
    )
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

  it("points the sheet menu item at the root path, not the drop-area route", async () => {
    window.history.replaceState({}, "", "/enviar")
    render(<App />)

    expect(
      await screen.findByRole("link", { name: "Planilha" })
    ).toHaveAttribute("href", "/")
  })
})
