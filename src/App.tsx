import { useState, useCallback, useEffect } from "react"
import { FileDropzone } from "@/components/FileDropzone"
import { UrlInput } from "@/components/UrlInput"
import { LoadErrorCard } from "@/components/LoadErrorCard"
import { DataTable } from "@/components/DataTable"
import { SchemaViewer } from "@/components/SchemaViewer"
import { StatsCards } from "@/components/StatsCards"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  FileSpreadsheet,
  Table2,
  ListTree,
  X,
  Github,
  Loader2,
  Download,
} from "lucide-react"
import {
  readParquetFile,
  loadMoreParquetData,
  type ParquetData,
  type ParquetSource,
} from "@/lib/parquet"
import { validateParquetUrl, fileNameFromUrl } from "@/lib/parquet-url"
import { buildLoadFailure, type LoadFailure } from "@/lib/remote-errors"
import { appendBatch, nextBatchSize } from "@/lib/pagination"

type ViewMode = "data" | "schema"

export default function App() {
  const [data, setData] = useState<ParquetData | null>(null)
  const [fileName, setFileName] = useState<string>("")
  const [currentSource, setCurrentSource] = useState<ParquetSource | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [initialError, setInitialError] = useState<LoadFailure | null>(null)
  const [loadMoreError, setLoadMoreError] = useState<LoadFailure | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>("data")

  const loadSource = useCallback(async (source: ParquetSource, name: string) => {
    setIsLoading(true)
    setInitialError(null)
    setLoadMoreError(null)

    try {
      // Determine initial load size based on file size (unknown for URLs, so be conservative)
      const sourceSize = source instanceof File ? source.size : null
      const initialLimit = sourceSize === null || sourceSize > 10 * 1024 * 1024 ? 500 : 1000

      const parquetData = await readParquetFile(source, initialLimit)
      setData(parquetData)
      setFileName(name)
      setCurrentSource(source)
    } catch (err) {
      console.error("Error reading parquet file:", err)
      // Local files can't be retried remotely — buildLoadFailure leaves info
      // null for them, so the error card renders no retry entry.
      setInitialError(buildLoadFailure(err, !(source instanceof File)))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const handleFileSelect = useCallback(
    (file: File) => loadSource(file, file.name),
    [loadSource]
  )

  const handleUrlSelect = useCallback(
    (url: string) => loadSource({ url }, fileNameFromUrl(url)),
    [loadSource]
  )

  // Re-run the most recent initial load. Only offered for temporary remote
  // failures; on success loadSource repopulates `data`, restoring the view.
  const handleRetryInitialLoad = useCallback(() => {
    if (!currentSource || isLoading) return
    loadSource(currentSource, fileName)
  }, [currentSource, fileName, isLoading, loadSource])

  // Support deep links: ?url=https://... opens the file on page load
  useEffect(() => {
    const param = new URLSearchParams(window.location.search).get("url")
    if (param) {
      const result = validateParquetUrl(param)
      if (result.ok) {
        handleUrlSelect(result.url)
      }
    }
  }, [handleUrlSelect])

  const handleLoadMore = useCallback(async () => {
    if (!currentSource || !data || !data.hasMore || isLoadingMore) return

    setIsLoadingMore(true)
    try {
      const batchSize = nextBatchSize(data.metadata.fileSize)
      // `data.loadedRows` is the offset of the failed (or next) batch: on
      // retry this re-requests exactly the rows that never arrived, never the
      // rows already shown.
      const batch = await loadMoreParquetData(
        currentSource,
        data.loadedRows,
        batchSize
      )

      // appendBatch only runs after a successful fetch: on failure the
      // existing rows, loadedRows and remaining count are left untouched.
      setData((prev) =>
        prev
          ? { ...prev, ...appendBatch(prev, batch, data.loadedRows) }
          : prev
      )
      setLoadMoreError(null)
    } catch (err) {
      console.error("Error loading more data:", err)
      setLoadMoreError(
        buildLoadFailure(err, !(currentSource instanceof File))
      )
    } finally {
      setIsLoadingMore(false)
    }
  }, [currentSource, data, isLoadingMore])

  const handleReset = useCallback(() => {
    setData(null)
    setFileName("")
    setCurrentSource(null)
    setInitialError(null)
    setLoadMoreError(null)
    setViewMode("data")
  }, [])

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100">
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-white/80 border-b">
        <div className="container mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-primary to-primary/80 text-primary-foreground">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-lg font-bold">Parquet Visualizer</h1>
              <p className="text-xs text-muted-foreground">
                View and explore parquet files in your browser
              </p>
            </div>
          </div>

          <a
            href="https://github.com/albatross-core/parquet-visualizer"
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 rounded-lg hover:bg-muted transition-colors"
          >
            <Github className="w-5 h-5" />
          </a>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        {!data && !isLoading && (
          <div className="max-w-2xl mx-auto space-y-8">
            <div className="text-center space-y-4">
              <h2 className="text-3xl font-bold tracking-tight">
                Visualize Your Parquet Files
              </h2>
              <p className="text-muted-foreground">
                Upload a parquet file to view its schema, metadata, and data.
                Everything happens in your browser - no data is sent to any
                server.
              </p>
            </div>

            <FileDropzone onFileSelect={handleFileSelect} isLoading={isLoading} />

            <div className="flex items-center gap-4">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground uppercase">or</span>
              <div className="h-px flex-1 bg-border" />
            </div>

            <UrlInput onUrlSubmit={handleUrlSelect} isLoading={isLoading} />

            {initialError && (
              <LoadErrorCard
                message={initialError.message}
                info={initialError.info}
                // Retry only for temporary remote failures; permanent link
                // failures and local-file errors pass no handler.
                onRetry={
                  initialError.info?.kind === "temporary"
                    ? handleRetryInitialLoad
                    : undefined
                }
                isRetrying={isLoading}
              />
            )}
          </div>
        )}

        {isLoading && (
          <div className="flex flex-col items-center justify-center gap-4 py-20">
            <Loader2 className="w-10 h-10 animate-spin text-primary" />
            <p className="text-muted-foreground">Loading parquet file...</p>
          </div>
        )}

        {data && !isLoading && (
          <div className="space-y-6">
            {/* File Info Bar */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-primary/10">
                  <FileSpreadsheet className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium">{fileName}</p>
                  <p className="text-sm text-muted-foreground">
                    Showing {data.loadedRows.toLocaleString()} of {data.metadata.numRows.toLocaleString()} rows,{" "}
                    {data.columns.length} columns
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={handleReset}>
                <X className="w-4 h-4 mr-1" />
                Close
              </Button>
            </div>

            {/* Warning for large files */}
            {data.hasMore && data.metadata.numRows > 10000 && (
              <Card className="border-amber-500/50 bg-amber-500/5">
                <CardContent className="p-4">
                  <p className="text-sm text-amber-700">
                    Large file detected. Data is loaded in batches for better performance.
                    {data.metadata.numRows > 100000 && " Consider loading only what you need."}
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Stats */}
            <StatsCards metadata={data.metadata} />

            {/* View Switcher */}
            <Card>
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg">
                    {viewMode === "data" ? "Data Preview" : "Schema"}
                  </CardTitle>
                  <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
                    <Button
                      variant={viewMode === "data" ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => setViewMode("data")}
                      className="gap-1"
                    >
                      <Table2 className="w-4 h-4" />
                      Data
                    </Button>
                    <Button
                      variant={viewMode === "schema" ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => setViewMode("schema")}
                      className="gap-1"
                    >
                      <ListTree className="w-4 h-4" />
                      Schema
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {viewMode === "data" ? (
                  <div className="space-y-4">
                    <DataTable data={data} />

                    {/* Inline failure: rows already loaded stay rendered above.
                        Permanent link failures remove the retry entry. */}
                    {loadMoreError && (
                      <LoadErrorCard
                        message={loadMoreError.message}
                        info={loadMoreError.info}
                        onRetry={
                          loadMoreError.info?.kind === "temporary"
                            ? handleLoadMore
                            : undefined
                        }
                        isRetrying={isLoadingMore}
                      />
                    )}

                    {/* Load More Button — hidden while a temporary failure is
                        shown (the card owns the retry), disabled permanently
                        when the link has expired. */}
                    {data.hasMore &&
                      !(
                        loadMoreError &&
                        loadMoreError.info?.kind === "temporary"
                      ) && (
                        <div className="flex items-center justify-center gap-4 pt-4">
                          <Button
                            onClick={handleLoadMore}
                            disabled={
                              isLoadingMore ||
                              loadMoreError?.info?.kind === "permanent"
                            }
                            variant="outline"
                            className="gap-2"
                          >
                            {isLoadingMore ? (
                              <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Loading...
                              </>
                            ) : (
                              <>
                                <Download className="w-4 h-4" />
                                Load More Rows
                              </>
                            )}
                          </Button>
                          <span className="text-sm text-muted-foreground">
                            {(data.metadata.numRows - data.loadedRows).toLocaleString()} rows remaining
                          </span>
                        </div>
                      )}
                  </div>
                ) : (
                  <SchemaViewer schema={data.metadata.schema} />
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t mt-auto">
        <div className="container mx-auto px-4 py-6 text-center text-sm text-muted-foreground">
          <p>
            Built with{" "}
            <a
              href="https://github.com/kylebarron/parquet-wasm"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
            >
              parquet-wasm
            </a>
            . No data leaves your browser.
          </p>
        </div>
      </footer>
    </div>
  )
}
