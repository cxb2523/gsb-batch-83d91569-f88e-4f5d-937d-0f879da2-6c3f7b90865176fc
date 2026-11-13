import { Fragment, useState } from "react"
import { formatDistanceToNowStrict } from "date-fns"
import { AlertTriangle } from "lucide-react"
import type {
  CollectionAlert,
  ScanStatus,
  ScanSummary,
} from "@shared/types"
import { StatusBadge, type StatusTone } from "@/components/app/StatusBadge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useRepoScans } from "@/hooks/useRepoDetail"

const STATUS_TONES: Record<ScanStatus, StatusTone> = {
  complete: "success",
  pending: "warning",
  running: "info",
  failed: "danger",
}

function summaryNumber(
  summary: Record<string, unknown> | null,
  key: string,
): number | null {
  const value = summary?.[key]
  return typeof value === "number" ? value : null
}

function healthScore(summary: Record<string, unknown> | null): number | null {
  const health = summary?.health
  if (!health || typeof health !== "object") return null
  const score = (health as { score?: unknown }).score
  return typeof score === "number" ? score : null
}

function collectionAlerts(
  summary: Record<string, unknown> | null,
): CollectionAlert[] {
  const raw = summary?.collectionAlerts
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (entry): entry is CollectionAlert =>
      typeof entry === "object" &&
      entry !== null &&
      typeof (entry as CollectionAlert).source === "string" &&
      typeof (entry as CollectionAlert).message === "string",
  )
}

function relativeDate(value: string): string {
  return formatDistanceToNowStrict(new Date(value), { addSuffix: true })
}

function ScanDetails({ scan }: { scan: ScanSummary }) {
  const score = healthScore(scan.summary)
  const detected = summaryNumber(scan.summary, "toolsDetected")
  const checked = summaryNumber(scan.summary, "toolsChecked")

  if (scan.status === "failed") {
    return (
      <p className="text-sm text-destructive">
        {scan.error ?? "The scan failed without an error message."}
      </p>
    )
  }

  if (scan.status !== "complete") {
    return (
      <p className="text-sm text-muted-foreground">
        This scan is still {scan.status}.
      </p>
    )
  }

  const alerts = collectionAlerts(scan.summary)

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div>
        <p className="text-xs text-muted-foreground">Repository health</p>
        <p className="text-sm font-medium">
          {score === null ? "—" : score.toFixed(1)}
        </p>
      </div>
      <div>
        <p className="text-xs text-muted-foreground">Tools detected</p>
        <p className="text-sm font-medium">{detected ?? "—"}</p>
      </div>
      <div>
        <p className="text-xs text-muted-foreground">Tools checked</p>
        <p className="text-sm font-medium">{checked ?? "—"}</p>
      </div>
      {alerts.length > 0 ? (
        <div className="sm:col-span-3">
          <p className="flex items-center gap-1 text-xs font-medium text-amber-600 dark:text-amber-400">
            <AlertTriangle className="size-3.5" aria-hidden="true" />
            {alerts.length} data source{alerts.length === 1 ? "" : "s"}{" "}
            failed during collection
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {alerts.map((alert, index) => (
              <li key={`${alert.source}-${index}`}>
                <span className="font-medium">{alert.source}</span>
                {alert.message ? <span>: {alert.message}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function ScanMobileCard({
  scan,
  expanded,
  onToggle,
}: {
  scan: ScanSummary
  expanded: boolean
  onToggle: () => void
}) {
  const score = healthScore(scan.summary)

  return (
    <div className="rounded-lg border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full flex-col gap-2 rounded-lg p-3 text-left transition-colors hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">
            {relativeDate(scan.createdAt)}
          </span>
          <StatusBadge tone={STATUS_TONES[scan.status]}>
            {scan.status}
          </StatusBadge>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>Health {score === null ? "—" : score.toFixed(1)}</span>
          <span>
            {scan.completedAt
              ? `Completed ${relativeDate(scan.completedAt)}`
              : "Not completed"}
          </span>
        </div>
      </button>
      {expanded ? (
        <div className="border-t p-3">
          <ScanDetails scan={scan} />
        </div>
      ) : null}
    </div>
  )
}

export function ScanHistory({ repoId }: { repoId: string }) {
  const scansQuery = useRepoScans(repoId)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const scans = scansQuery.data?.scans.slice(0, 3) ?? []

  function toggle(scanId: string) {
    setExpandedId((current) => (current === scanId ? null : scanId))
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Scan history</CardTitle>
        <CardDescription>The three most recent scans.</CardDescription>
      </CardHeader>
      <CardContent>
        {scansQuery.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : scansQuery.isError ? (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <p className="text-sm text-muted-foreground">
              Could not load scan history.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => scansQuery.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : scans.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No scans yet.
          </p>
        ) : (
          <>
            <div className="space-y-2 md:hidden">
              {scans.map((scan) => (
                <ScanMobileCard
                  key={scan.id}
                  scan={scan}
                  expanded={expandedId === scan.id}
                  onToggle={() => toggle(scan.id)}
                />
              ))}
            </div>
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Started</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Health</TableHead>
                    <TableHead>Completed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {scans.map((scan) => {
                    const expanded = expandedId === scan.id
                    const score = healthScore(scan.summary)
                    return (
                      <Fragment key={scan.id}>
                        <TableRow
                          className="cursor-pointer"
                          tabIndex={0}
                          aria-expanded={expanded}
                          onClick={() => toggle(scan.id)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault()
                              toggle(scan.id)
                            }
                          }}
                        >
                          <TableCell
                            title={new Date(scan.createdAt).toLocaleString()}
                          >
                            {relativeDate(scan.createdAt)}
                          </TableCell>
                          <TableCell>
                            <StatusBadge tone={STATUS_TONES[scan.status]}>
                              {scan.status}
                            </StatusBadge>
                          </TableCell>
                          <TableCell>
                            {score === null ? "—" : score.toFixed(1)}
                          </TableCell>
                          <TableCell>
                            {scan.completedAt
                              ? relativeDate(scan.completedAt)
                              : "—"}
                          </TableCell>
                        </TableRow>
                        {expanded ? (
                          <TableRow>
                            <TableCell colSpan={4} className="bg-muted/30">
                              <ScanDetails scan={scan} />
                            </TableCell>
                          </TableRow>
                        ) : null}
                      </Fragment>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
