import { useMemo, useState } from "react"
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  ArrowUpDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  FileSpreadsheetIcon,
  InfoIcon,
  XIcon,
} from "lucide-react"

import { SheetFileInput } from "@/components/SheetFileInput"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { ControlSheetResponse } from "@/lib/control-sheet"
import { rowKey } from "@/lib/control-sheet"
import { cn } from "@/lib/utils"

interface WorkGroupsProps {
  data: ControlSheetResponse
  status: "idle" | "loading" | "starting"
  errorDetail: string | null
  onReplaceFile: (file: File) => void
  onGenerate: (rowNumber: number) => void
}

type WorkStatus = "ready" | "blocked" | "unsupported"

interface WorkRow {
  key: string
  rowNumber: number
  pasta: string
  demanda: string
  title: string
  detail: string
  especialista: string
  kickOff: string
  captureOrigin: string
  reportReady: string
  status: WorkStatus
  problem: string
  solution: string
}

const statusOptions = [
  { label: "Todas as situações", value: "all" },
  { label: "Pronto para gerar", value: "ready" },
  { label: "Não dá para gerar", value: "blocked" },
  { label: "Ainda não suportado", value: "unsupported" },
]

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("pt-BR")
}

function toRows(data: ControlSheetResponse): WorkRow[] {
  const readyRows = data.engagements.map((engagement) => ({
    key: rowKey(engagement.row),
    rowNumber: engagement.row.row_number,
    pasta: engagement.row.pasta ?? "—",
    demanda: engagement.demanda,
    title: engagement.razao_social,
    detail: "",
    especialista: engagement.especialista,
    kickOff: engagement.kick_off,
    captureOrigin: engagement.capture_origin,
    reportReady: engagement.report_ready_text,
    status: "ready" as const,
    problem: "",
    solution: "",
  }))

  const blockedRows = data.stop_conditions.map((stop) => ({
    key: rowKey(stop.row),
    rowNumber: stop.row.row_number,
    pasta: stop.row.pasta ?? "—",
    demanda: stop.demanda || "—",
    title: stop.razao_social || "—",
    detail: "",
    especialista: stop.especialista || "—",
    kickOff: stop.kick_off || "—",
    captureOrigin: stop.link,
    reportReady: stop.report_ready_text,
    status: "blocked" as const,
    problem: stop.problema,
    solution: stop.solucao,
  }))

  const unsupportedRows = data.unsupported_rows.rows.map((item) => ({
    key: rowKey(item.row),
    rowNumber: item.row.row_number,
    pasta: item.row.pasta ?? "—",
    demanda: item.demanda || "—",
    title: item.razao_social || "—",
    detail: "",
    especialista: item.especialista || "—",
    kickOff: item.kick_off || "—",
    captureOrigin: item.link,
    reportReady: item.report_ready_text,
    status: "unsupported" as const,
    problem: item.tema,
    solution: item.explicacao,
  }))

  return [...readyRows, ...blockedRows, ...unsupportedRows]
}

function SortableHeader({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick}>
      {label}
      <ArrowUpDownIcon data-icon="inline-end" aria-hidden="true" />
    </Button>
  )
}

function StatusBadge({ row }: { row: WorkRow }) {
  if (row.status === "ready") {
    return <Badge>Pronto</Badge>
  }
  if (row.status === "blocked") {
    return (
      <div className="flex items-center gap-1">
        <Badge variant="destructive">Bloqueada</Badge>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Por que a linha ${row.rowNumber} está bloqueada?`}
              />
            }
          >
            <InfoIcon aria-hidden="true" />
          </TooltipTrigger>
          <TooltipContent className="flex max-w-72 flex-col items-start gap-1 rounded-sm">
            <p className="font-medium">{row.problem}</p>
            <p>{row.solution}</p>
          </TooltipContent>
        </Tooltip>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1">
      <Badge className="border-amber-300 bg-amber-100 text-amber-950 hover:bg-amber-100 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
        Tema sem suporte
      </Badge>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={`Por que a linha ${row.rowNumber} ainda não é suportada?`}
            />
          }
        >
          <InfoIcon aria-hidden="true" />
        </TooltipTrigger>
        <TooltipContent className="flex max-w-72 flex-col items-start gap-1 rounded-sm">
          <p className="font-medium">{row.problem}</p>
          <p>{row.solution}</p>
        </TooltipContent>
      </Tooltip>
    </div>
  )
}

export function WorkGroups({
  data,
  status,
  errorDetail,
  onReplaceFile,
  onGenerate,
}: WorkGroupsProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<WorkStatus | "all">("all")
  const [reportReadyFilter, setReportReadyFilter] = useState("all")
  const [sorting, setSorting] = useState<SortingState>([])
  const isLoading = status !== "idle"
  const allRows = useMemo(() => toRows(data), [data])
  const reportReadyOptions = useMemo(() => {
    const values = new Map<string, string>()
    let hasBlank = false

    for (const row of allRows) {
      const value = row.reportReady.trim()
      if (!value) {
        hasBlank = true
        continue
      }
      const key = normalize(value)
      if (!values.has(key)) {
        values.set(key, value)
      }
    }

    const options = [...values.entries()]
      .sort(([, left], [, right]) => left.localeCompare(right, "pt-BR"))
      .map(([key, label]) => ({
        label,
        value: `value:${key}`,
      }))

    return [
      { label: "todos", value: "all" },
      ...options,
      ...(hasBlank ? [{ label: "em branco", value: "blank" }] : []),
    ]
  }, [allRows])

  const selectedEngagement = data.engagements.find(
    (engagement) => rowKey(engagement.row) === selected
  )

  const filteredRows = useMemo(() => {
    const normalizedQuery = normalize(query.trim())
    return allRows.filter((row) => {
      if (statusFilter !== "all" && row.status !== statusFilter) {
        return false
      }
      if (reportReadyFilter === "blank" && row.reportReady.trim()) {
        return false
      }
      if (
        reportReadyFilter.startsWith("value:") &&
        normalize(row.reportReady.trim()) !== reportReadyFilter.slice(6)
      ) {
        return false
      }
      if (!normalizedQuery) {
        return true
      }
      return normalize(
        [
          row.pasta,
          row.demanda,
          row.title,
          row.detail,
          row.especialista,
          row.kickOff,
          row.captureOrigin,
          row.reportReady,
          row.problem,
          row.solution,
        ].join(" ")
      ).includes(normalizedQuery)
    })
  }, [allRows, query, reportReadyFilter, statusFilter])

  const columns = useMemo<ColumnDef<WorkRow>[]>(
    () => [
      {
        id: "select",
        header: () => <span className="sr-only">Selecionar</span>,
        cell: ({ row }) => {
          const item = row.original
          if (item.status !== "ready") {
            return null
          }
          return (
            <Checkbox
              checked={selected === item.key}
              disabled={isLoading}
              onCheckedChange={() =>
                setSelected((previous) =>
                  previous === item.key ? null : item.key
                )
              }
              aria-label={`Selecionar ${item.title}, pasta ${item.pasta === "—" ? "sem pasta" : item.pasta}, linha ${item.rowNumber}`}
            />
          )
        },
        enableSorting: false,
      },
      {
        accessorKey: "pasta",
        header: ({ column }) => (
          <SortableHeader
            label="Pasta"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          />
        ),
        cell: ({ row }) => (
          <span className="font-medium">{row.original.pasta}</span>
        ),
      },
      {
        accessorKey: "demanda",
        header: ({ column }) => (
          <SortableHeader
            label="Demanda"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          />
        ),
      },
      {
        accessorKey: "title",
        header: ({ column }) => (
          <SortableHeader
            label="Empresa / Tema"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          />
        ),
        cell: ({ row }) => (
          <div className="flex max-w-md min-w-64 flex-col gap-1 whitespace-normal">
            <span className="font-medium text-foreground">
              {row.original.title}
            </span>
            {row.original.detail && (
              <span className="text-xs text-muted-foreground">
                {row.original.detail}
              </span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "especialista",
        header: "Especialista",
      },
      {
        accessorKey: "kickOff",
        header: "Início",
      },
      {
        accessorKey: "captureOrigin",
        header: "Link do site",
        cell: ({ row }) => {
          const value = row.original.captureOrigin
          return /^https?:\/\/\S+$/i.test(value) ? (
            <a
              className="block font-medium whitespace-nowrap text-foreground underline underline-offset-4"
              href={value}
              target="_blank"
              rel="noreferrer"
            >
              {value}
            </a>
          ) : value ? (
            value
          ) : (
            "—"
          )
        },
      },
      {
        accessorKey: "reportReady",
        header: "Relatório pronto?",
        cell: ({ row }) => row.original.reportReady || "—",
      },
      {
        accessorKey: "status",
        header: ({ column }) => (
          <SortableHeader
            label="Situação"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          />
        ),
        cell: ({ row }) => <StatusBadge row={row.original} />,
      },
    ],
    [isLoading, selected]
  )

  // TanStack Table intentionally exposes mutable helpers; React Compiler
  // correctly leaves this component out of automatic memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageIndex: 0,
        pageSize: 10,
      },
    },
  })

  const filtersActive =
    query.trim() !== "" || statusFilter !== "all" || reportReadyFilter !== "all"
  const generateLabel =
    status === "starting"
      ? "Iniciando geração…"
      : selectedEngagement
        ? "Gerar relatório"
        : "Selecione um trabalho"
  const visibleRows = table.getRowModel().rows
  const pageStart =
    filteredRows.length === 0
      ? 0
      : table.getState().pagination.pageIndex *
          table.getState().pagination.pageSize +
        1
  const pageEnd = Math.min(
    pageStart + visibleRows.length - 1,
    filteredRows.length
  )

  function resetFilters() {
    setQuery("")
    setStatusFilter("all")
    setReportReadyFilter("all")
    table.setPageIndex(0)
  }

  return (
    <TooltipProvider>
      <div className="mt-10 flex w-full min-w-0 flex-col gap-8">
        <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <FileSpreadsheetIcon aria-hidden="true" className="size-5" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-semibold tracking-wide text-primary uppercase">
                Planilha enviada
              </p>
              <p className="truncate text-base font-semibold text-foreground">
                {data.filename}
              </p>
            </div>
          </div>
          <SheetFileInput
            label="Enviar outra planilha"
            size="sm"
            variant="secondary"
            disabled={isLoading}
            onFile={onReplaceFile}
          />
        </div>

        <p
          role="status"
          aria-live="polite"
          className="min-h-4 text-sm text-muted-foreground"
        >
          {status === "loading"
            ? "Lendo a planilha, isso pode levar um instante…"
            : ""}
        </p>
        {errorDetail && (
          <p role="alert" className="text-sm font-medium text-destructive">
            {errorDetail}
          </p>
        )}

        <section
          aria-labelledby="work-table-heading"
          className="min-w-0 text-left"
        >
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="flex flex-col gap-2">
                <h2
                  id="work-table-heading"
                  className="font-display text-2xl font-semibold text-heading"
                >
                  Demandas da planilha
                </h2>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                  <span>
                    <strong className="text-foreground">
                      {data.engagements.length}
                    </strong>{" "}
                    <span>Pronto para gerar</span>
                  </span>
                  <span>
                    <strong className="text-foreground">
                      {data.stop_conditions.length}
                    </strong>{" "}
                    <span>Não dá para gerar</span>
                  </span>
                  <span>
                    <strong className="text-foreground">
                      {data.unsupported_rows.total}
                    </strong>{" "}
                    <span>Ainda não suportado</span>
                  </span>
                </div>
              </div>
              <Button
                size="lg"
                disabled={!selectedEngagement || isLoading}
                onClick={() =>
                  selectedEngagement &&
                  onGenerate(selectedEngagement.row.row_number)
                }
              >
                {generateLabel}
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Input
                className="w-full rounded-sm sm:max-w-sm"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  table.setPageIndex(0)
                }}
                aria-label="Filtrar Demandas"
                placeholder="Filtrar por Pasta, Demanda, empresa…"
              />
              <Select
                items={statusOptions}
                value={statusFilter}
                onValueChange={(value) => {
                  setStatusFilter((value ?? "all") as WorkStatus | "all")
                  table.setPageIndex(0)
                }}
              >
                <SelectTrigger
                  aria-label="Filtrar por situação"
                  className="rounded-sm"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-sm">
                  <SelectGroup>
                    {statusOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Select
                items={reportReadyOptions}
                value={reportReadyFilter}
                onValueChange={(value) => {
                  setReportReadyFilter(value ?? "all")
                  table.setPageIndex(0)
                }}
              >
                <SelectTrigger
                  aria-label="Filtrar por Relatório pronto?"
                  className="rounded-sm"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-sm">
                  <SelectGroup>
                    {reportReadyOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {filtersActive && (
                <Button variant="ghost" size="sm" onClick={resetFilters}>
                  Limpar
                  <XIcon data-icon="inline-end" aria-hidden="true" />
                </Button>
              )}
            </div>

            <div className="overflow-hidden rounded-md border bg-canvas">
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <TableRow key={headerGroup.id}>
                      {headerGroup.headers.map((header) => (
                        <TableHead key={header.id}>
                          {header.isPlaceholder
                            ? null
                            : flexRender(
                                header.column.columnDef.header,
                                header.getContext()
                              )}
                        </TableHead>
                      ))}
                    </TableRow>
                  ))}
                </TableHeader>
                <TableBody>
                  {visibleRows.length ? (
                    visibleRows.map((row) => (
                      <TableRow
                        key={row.original.key}
                        data-status={row.original.status}
                        data-state={
                          selected === row.original.key ? "selected" : undefined
                        }
                        className={cn(
                          row.original.status === "blocked" &&
                            "bg-destructive/5 hover:bg-destructive/10 [&>td:first-child]:border-l-2 [&>td:first-child]:border-l-destructive",
                          row.original.status === "unsupported" &&
                            "bg-amber-50/70 hover:bg-amber-100/70 dark:bg-amber-950/20 dark:hover:bg-amber-950/30 [&>td:first-child]:border-l-2 [&>td:first-child]:border-l-amber-400"
                        )}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext()
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={columns.length}
                        className="h-24 text-center text-muted-foreground"
                      >
                        Nenhuma Demanda corresponde aos filtros.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-muted-foreground">
                {selectedEngagement
                  ? `1 trabalho selecionado · ${pageStart}–${pageEnd} de ${filteredRows.length}`
                  : `${pageStart}–${pageEnd} de ${filteredRows.length} Demandas`}
              </p>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">Linhas por página</span>
                  <Select
                    items={[
                      { label: "10", value: "10" },
                      { label: "25", value: "25" },
                      { label: "50", value: "50" },
                    ]}
                    value={String(table.getState().pagination.pageSize)}
                    onValueChange={(value) =>
                      table.setPageSize(Number(value ?? "10"))
                    }
                  >
                    <SelectTrigger
                      size="sm"
                      aria-label="Linhas por página"
                      className="w-16 !rounded-sm"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-sm">
                      <SelectGroup>
                        {[10, 25, 50].map((pageSize) => (
                          <SelectItem key={pageSize} value={String(pageSize)}>
                            {pageSize}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </div>
                <span className="text-sm font-medium">
                  Página {table.getState().pagination.pageIndex + 1} de{" "}
                  {Math.max(table.getPageCount(), 1)}
                </span>
                <div className="flex gap-1">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={!table.getCanPreviousPage()}
                    onClick={() => table.previousPage()}
                    aria-label="Página anterior"
                  >
                    <ChevronLeftIcon aria-hidden="true" />
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={!table.getCanNextPage()}
                    onClick={() => table.nextPage()}
                    aria-label="Próxima página"
                  >
                    <ChevronRightIcon aria-hidden="true" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </TooltipProvider>
  )
}

export default WorkGroups
