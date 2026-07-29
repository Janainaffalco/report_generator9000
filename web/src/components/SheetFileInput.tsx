import { useRef } from "react"

import { Button } from "@/components/ui/button"

const SHEET_ACCEPT =
  ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

interface SheetFileInputProps {
  label: string
  /** The picker's accessible name, when it should differ from the button's. */
  inputLabel?: string
  disabled?: boolean
  size?: "sm" | "lg"
  variant?: "default" | "secondary"
  className?: string
  onFile: (file: File) => void
}

/** The hidden .xlsx picker plus the button that opens it. */
export function SheetFileInput({
  label,
  inputLabel = label,
  disabled = false,
  size = "lg",
  variant = "default",
  className,
  onFile,
}: SheetFileInputProps) {
  const input = useRef<HTMLInputElement>(null)

  return (
    <div>
      <input
        ref={input}
        aria-label={inputLabel}
        className="sr-only"
        type="file"
        accept={SHEET_ACCEPT}
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ""
          if (file) {
            onFile(file)
          }
        }}
      />
      <Button
        className={className}
        size={size}
        variant={variant}
        disabled={disabled}
        onClick={() => input.current?.click()}
      >
        {label}
      </Button>
    </div>
  )
}

export default SheetFileInput
