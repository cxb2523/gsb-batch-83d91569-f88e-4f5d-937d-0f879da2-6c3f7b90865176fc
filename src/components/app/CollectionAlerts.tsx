import { AlertTriangle } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { cn } from "@/lib/utils"
import type { CollectionAlert } from "@shared/types"

export function CollectionAlertsBanner({
  alerts,
}: {
  alerts: CollectionAlert[]
}) {
  if (alerts.length === 0) return null

  return (
    <Alert
      data-testid="collection-alerts"
      className="border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <AlertTriangle className="size-4" />
      <AlertTitle>
        {alerts.length} data source{alerts.length === 1 ? "" : "s"} could not
        be collected
      </AlertTitle>
      <AlertDescription
        className={cn(
          "text-amber-800 dark:text-amber-300",
          "[&_p]:leading-relaxed",
        )}
      >
        <p>
          This scan completed with partial data. The metrics below that depend
          on these sources are calculated with the data that was available.
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          {alerts.map((alert, index) => (
            <li key={`${alert.source}-${index}`}>
              <span className="font-medium">{alert.source}</span>
              {alert.message ? <span>: {alert.message}</span> : null}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}
