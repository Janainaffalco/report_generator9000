import { UploadIcon } from "lucide-react"

import { InlineNotice } from "@/components/InlineNotice"
import { SheetFileInput } from "@/components/SheetFileInput"
import { Badge } from "@/components/ui/badge"

interface UploadPanelProps {
  status: "idle" | "loading"
  errorDetail: string | null
  onFile: (file: File) => void
}

export function UploadPanel({ status, errorDetail, onFile }: UploadPanelProps) {
  const isLoading = status === "loading"

  function handleFiles(files: FileList | null) {
    const file = files?.[0]
    if (file) {
      onFile(file)
    }
  }

  return (
    <section className="flex w-full max-w-4xl flex-col items-center text-center">
      <h1 className="mt-4 max-w-3xl font-display text-[44px] leading-[1.15] font-bold tracking-[-0.8px] text-heading">
        Arraste sua <span className="text-gradient-red">planilha</span> de controle. O resto é com a gente.
      </h1>
      <p className="mt-5 max-w-2xl text-base leading-6 text-foreground">
        A gente lê a planilha, visita o site do cliente e prepara o relatório
        para você conferir.
      </p>

      <div
        data-testid="control-sheet-dropzone"
        aria-busy={isLoading}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          handleFiles(event.dataTransfer.files)
        }}
        className="mt-10 flex min-h-80 w-full max-w-3xl flex-col items-center justify-center rounded-lg border border-border bg-canvas px-8 py-12"
      >
        <div className="flex size-16 items-center justify-center rounded-full bg-muted">
          <UploadIcon aria-hidden="true" />
        </div>
        <h2 className="mt-5 font-display text-2xl font-semibold text-heading">
          Solte a planilha aqui
        </h2>
        <p className="mt-2 text-base text-foreground">
          ou clique para escolher o arquivo no seu computador
        </p>
        <div className="mt-5 flex items-center gap-3">
          <Badge variant="secondary">.xlsx</Badge>
          <span className="text-xs text-muted-foreground">
            aba “LV e Site” · a mesma planilha que você já usa
          </span>
        </div>
        <SheetFileInput
          className="mt-7 rounded-full"
          label="Escolher planilha"
          inputLabel="Arquivo de planilha"
          disabled={isLoading}
          onFile={onFile}
        />
        <p
          role="status"
          aria-live="polite"
          className="mt-4 min-h-4 text-sm text-muted-foreground"
        >
          {isLoading ? "Lendo a planilha, isso pode levar um instante…" : ""}
        </p>
      </div>

      {errorDetail && (
        <InlineNotice
          tone="error"
          title="Não foi possível usar esta planilha"
          className="mt-4 max-w-3xl"
        >
          {errorDetail}
        </InlineNotice>
      )}
    </section>
  )
}

export default UploadPanel
