import "@testing-library/jest-dom/vitest"

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { App } from "@/App"

function jsonResponse(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

beforeEach(() => {
  window.history.replaceState({}, "", "/enviar")
  vi.stubGlobal("fetch", vi.fn())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState({}, "", "/")
})

it("shows a login form instead of the planilha drop while signed out", async () => {
  vi.mocked(fetch).mockResolvedValue(jsonResponse(401, { detail: "É preciso entrar para continuar." }))

  render(<App />)

  expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument()
  expect(screen.getByLabelText("Senha")).toBeInTheDocument()
  expect(
    screen.queryByTestId("control-sheet-dropzone")
  ).not.toBeInTheDocument()
  expect(screen.queryByText("Pronto para gerar")).not.toBeInTheDocument()
  expect(
    screen.queryByRole("heading", { name: "Relatórios anteriores" })
  ).not.toBeInTheDocument()
})

it("takes the consultant into the app after a correct password", async () => {
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    if (url === "/api/session") {
      return jsonResponse(401)
    }
    if (url === "/api/login" && method === "POST") {
      return jsonResponse(204)
    }
    if (url === "/api/control-sheets") {
      return jsonResponse(200, [])
    }
    return jsonResponse(404)
  })

  render(<App />)
  await screen.findByRole("heading", { name: "Entrar" })
  fireEvent.change(screen.getByLabelText("Senha"), {
    target: { value: "shared-password" },
  })
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }))

  expect(await screen.findByTestId("control-sheet-dropzone")).toBeInTheDocument()
  expect(
    screen.queryByRole("heading", { name: "Entrar" })
  ).not.toBeInTheDocument()
})

it("stays on the login form with an error after a wrong password", async () => {
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    if (url === "/api/session") {
      return jsonResponse(401)
    }
    if (url === "/api/login" && method === "POST") {
      return jsonResponse(401, { detail: "Senha incorreta." })
    }
    return jsonResponse(404)
  })

  render(<App />)
  await screen.findByRole("heading", { name: "Entrar" })
  fireEvent.change(screen.getByLabelText("Senha"), {
    target: { value: "wrong" },
  })
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("Senha incorreta.")
  expect(screen.getByRole("heading", { name: "Entrar" })).toBeInTheDocument()
  expect(
    screen.queryByTestId("control-sheet-dropzone")
  ).not.toBeInTheDocument()
})

it("returns to the login form after logout", async () => {
  let signedIn = true
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    if (url === "/api/session") {
      return jsonResponse(signedIn ? 200 : 401, { status: "ok" })
    }
    if (url === "/api/logout" && method === "POST") {
      signedIn = false
      return jsonResponse(204)
    }
    if (url === "/api/control-sheets") {
      return jsonResponse(200, [])
    }
    return jsonResponse(404)
  })

  render(<App />)
  expect(await screen.findByTestId("control-sheet-dropzone")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Sair" }))

  expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument()
  expect(
    screen.queryByTestId("control-sheet-dropzone")
  ).not.toBeInTheDocument()
})

it("does not show a report at a review URL until after login", async () => {
  window.history.replaceState({}, "", "/relatorios/past-run")
  let signedIn = false
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    if (url === "/api/session") {
      return jsonResponse(signedIn ? 200 : 401)
    }
    if (url === "/api/login" && method === "POST") {
      signedIn = true
      return jsonResponse(204)
    }
    if (url === "/api/runs/past-run") {
      return jsonResponse(200, {
        run_id: "past-run",
        sheet_id: "sheet",
        engagement: {
          row_number: 2,
          pasta: "40-2026",
          razao_social: "DENISE BARROS DE ALMEIDA",
        },
        outcome: "finished",
        current_stage: null,
        stages: [],
        stage_history: [],
        page_count: 5,
        status: "draft",
        filename: "relatorio.docx",
        reason: null,
        download_url: "/api/runs/past-run/download",
      })
    }
    if (url === "/api/runs/past-run/report") {
      return jsonResponse(200, {
        run_id: "past-run",
        status: "draft",
        page_count: 5,
        filename: "relatorio.docx",
        download_url: "/api/runs/past-run/download",
        pendencias: [],
        checks: [],
      })
    }
    return jsonResponse(404)
  })

  render(<App />)

  expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument()
  expect(screen.queryByText("DENISE BARROS DE ALMEIDA")).not.toBeInTheDocument()

  fireEvent.change(screen.getByLabelText("Senha"), {
    target: { value: "shared-password" },
  })
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }))

  expect(await screen.findByRole("button", { name: "Sair" })).toBeInTheDocument()
  expect(
    screen.queryByRole("heading", { name: "Entrar" })
  ).not.toBeInTheDocument()
  await waitFor(() => {
    expect(fetch).toHaveBeenCalledWith("/api/runs/past-run")
  })
})
