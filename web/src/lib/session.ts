export async function getSession(): Promise<boolean> {
  try {
    const response = await fetch("/api/session")
    return response.ok
  } catch {
    return false
  }
}

export async function login(password: string): Promise<
  { ok: true } | { ok: false; detail: string }
> {
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    })
    if (response.ok) {
      return { ok: true }
    }
    let detail = "Senha incorreta."
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === "string") {
        detail = body.detail
      }
    } catch {
      // keep the generic detail
    }
    return { ok: false, detail }
  } catch {
    return {
      ok: false,
      detail: "Não foi possível conectar ao servidor. Tente novamente.",
    }
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/logout", { method: "POST" })
  } catch {
    // Clearing local signed-in state still happens in the caller.
  }
}
