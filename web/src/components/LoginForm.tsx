import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { login } from "@/lib/session"

interface LoginFormProps {
  onSignedIn: () => void
}

export function LoginForm({ onSignedIn }: LoginFormProps) {
  const [password, setPassword] = useState("")
  const [status, setStatus] = useState<"idle" | "submitting">("idle")
  const [errorDetail, setErrorDetail] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setStatus("submitting")
    setErrorDetail(null)
    const result = await login(password)
    setStatus("idle")
    if (result.ok) {
      onSignedIn()
      return
    }
    setErrorDetail(result.detail)
  }

  return (
    <section className="flex w-full max-w-md flex-col items-center text-center">
      <h1 className="mt-4 font-display text-[44px] leading-[1.15] font-bold tracking-[-0.8px] text-heading">
        Entrar
      </h1>
      <p className="mt-5 text-base leading-6 text-foreground">
        Esta ferramenta não é pública. Digite a senha compartilhada.
      </p>
      <form
        className="mt-10 flex w-full flex-col items-stretch gap-4 text-left"
        onSubmit={(event) => void handleSubmit(event)}
      >
        <label className="text-sm font-medium" htmlFor="shared-password">
          Senha
        </label>
        <Input
          id="shared-password"
          type="password"
          autoComplete="current-password"
          value={password}
          disabled={status === "submitting"}
          onChange={(event) => setPassword(event.target.value)}
        />
        <Button type="submit" disabled={status === "submitting"}>
          Entrar
        </Button>
      </form>
      {errorDetail && (
        <p
          role="alert"
          className="mt-4 text-sm font-medium text-destructive"
        >
          {errorDetail}
        </p>
      )}
    </section>
  )
}
