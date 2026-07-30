import { FileSpreadsheetIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { RetainedSheet } from "@/lib/control-sheet"

interface RetainedSheetPickerProps {
  sheets: RetainedSheet[]
  onSelect: (sheetId: string) => void
}

const uploadTime = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
})

export function RetainedSheetPicker({
  sheets,
  onSelect,
}: RetainedSheetPickerProps) {
  return (
    <section className="mt-10 flex w-full max-w-3xl flex-col gap-6">
      <div>
        <h1 className="font-display text-3xl font-semibold text-heading">
          Escolha uma planilha
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Estas planilhas ficam no servidor por sete dias para você continuar o
          trabalho sem enviar o mesmo arquivo de novo.
        </p>
      </div>

      <ul className="flex flex-col gap-3">
        {sheets.map((sheet) => (
          <li key={sheet.sheet_id}>
            <Card>
              <CardContent className="flex items-center justify-between gap-5">
                <div className="flex min-w-0 items-center gap-3">
                  <FileSpreadsheetIcon
                    aria-hidden="true"
                    className="size-5 shrink-0 text-primary"
                  />
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{sheet.filename}</p>
                    <p className="text-sm text-muted-foreground">
                      Enviada em{" "}
                      {uploadTime.format(new Date(sheet.uploaded_at))}
                      {" · "}
                      {sheet.ready_count}{" "}
                      {sheet.ready_count === 1
                        ? "trabalho pronto"
                        : "trabalhos prontos"}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => onSelect(sheet.sheet_id)}
                >
                  Usar {sheet.filename}
                </Button>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>

      <a
        className="self-start text-sm font-semibold text-primary"
        href="/enviar"
      >
        Enviar nova planilha
      </a>
    </section>
  )
}
