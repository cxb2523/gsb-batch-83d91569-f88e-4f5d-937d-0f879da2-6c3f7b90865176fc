/**
 * PRISM Zustand Store
 * 
 * Centralized state management for the analytics platform.
 * Handles file upload, processing state, and results.
 * 
 * Security: All sensitive data is held only in memory and never persisted.
 */

import { create } from 'zustand';
import { loadSheetJS } from '@/lib/sheetjs-loader';
import type {
  PrismState,
  FileMetadata,
  ProcessingProgress,
  ProcessingError,
  DatasetSummary,
  VisualizationRecommendation,
  AIInsight,
  ChartConfig,
  AccessibilitySettings,
  WorkerMessage,
  WorkerResultPayload,
} from '@/types';
import { validateFile } from '@/security/validator';
// Inlined at build time so the worker can be started from a blob: URL (see getWorker)
import prismWorkerSource from '../workers/prism.worker.js?raw';

// ═══════════════════════════════════════════════════════════════════════════
// INITIAL STATE
// ═══════════════════════════════════════════════════════════════════════════

const initialAccessibility: AccessibilitySettings = {
  fontSize: 'normal',
  colorScheme: 'system',
  reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  sonificationEnabled: true,
  screenReaderMode: false,
};

const initialProgress: ProcessingProgress = {
  status: 'idle',
  progress: 0,
  message: '',
  accessibleMessage: '',
};

const initialState = {
  file: {
    metadata: null as FileMetadata | null,
    content: null as string | null,
    validationStatus: 'pending' as const,
    validationError: null as string | null,
    // Things the user must be told about how their file was read, for example
    // that a workbook had several sheets and only the first was analysed.
    // These are not errors: the analysis succeeded, but on less than the whole file.
    notices: [] as string[],
  },
  // Multi-dataset state
  datasets: [] as import('@/types').Dataset[],
  datasetLinks: [] as import('@/types').DatasetLink[],
  activeDatasetId: null as string | null,
  sheetOutcomes: [] as import('@/types').SheetOutcome[],
  
  processing: initialProgress,
  error: null as ProcessingError | null,
  results: {
    summary: null as DatasetSummary | null,
    recommendations: [] as VisualizationRecommendation[],
    insights: [] as AIInsight[],
    chartConfigs: [] as ChartConfig[],
  },
  customAnalysisResults: null as import('@/types').CustomAnalysisResult | null,
  accessibility: initialAccessibility,
  activeChartIndex: 0,
};

// ═══════════════════════════════════════════════════════════════════════════
// FILE READING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Upper bound on rows pulled out of a workbook. XLSX.read runs on the main
 * thread, so an unbounded sheet - a zip bomb still under the 500MB file limit -
 * would otherwise hang the UI with no recovery path.
 */
const MAX_SHEET_ROWS = 100000;

/**
 * Parser surface is pinned off deliberately: formulas, HTML rendering, number
 * formats, styles and VBA are all attacker-controlled and none of them are used
 * by PRISM - only cell values reach sheet_to_csv.
 */
const XLSX_READ_OPTIONS: Record<string, unknown> = {
  type: 'array',
  sheetRows: MAX_SHEET_ROWS,
  cellFormula: false,
  cellHTML: false,
  cellNF: false,
  cellStyles: false,
  bookVBA: false,
  bookDeps: false,
};

/** What a workbook parse produced, plus anything the user must be told about it. */
interface ParseResult {
  content: string;
  notices: string[];
}

/** One worksheet of a parsed workbook, as CSV, plus a truncation flag. */
interface ParsedSheet {
  name: string;
  /** CSV of the sheet, or null when this sheet alone could not be converted. */
  csv: string | null;
  /** Why csv is null. */
  error?: string;
  truncated: boolean;
}

/**
 * Rows spanned by a sheet's declared range. XLSX_READ_OPTIONS caps parsing at
 * MAX_SHEET_ROWS, so a sheet whose range still spans the cap was truncated
 * (a sheet with exactly MAX_SHEET_ROWS rows is a benign false positive).
 */
function sheetRowCount(sheet: unknown): number {
  const ref = (sheet as { '!ref'?: unknown })['!ref'];
  if (typeof ref !== 'string') return 0;
  const rows = Array.from(ref.matchAll(/[A-Z]+(\d+)/gi), (m) => parseInt(m[1]!, 10));
  if (rows.length === 0) return 0;
  if (rows.length === 1) return rows[0]!;
  return rows[1]! - rows[0]! + 1;
}

/**
 * Run `fn` against the SheetJS parser behind the Object.prototype tripwire.
 *
 * Security: this now runs SheetJS 0.20.3, vendored in public/vendor/ and loaded
 * on demand by src/lib/sheetjs-loader.ts. The previous npm build, xlsx@0.18.5,
 * was frozen and unpatchable, carrying prototype pollution (GHSA-4r6h-8v6p-xvw6)
 * reachable through exactly this call on bytes the user just dragged in.
 *
 * The Object.prototype bracket is kept even though 0.20.3 fixes that advisory.
 * It costs a set construction per upload, it is the only thing standing between
 * a future parser regression and the rest of the application, and this parser's
 * whole job is chewing on hostile input.
 */
async function withParserGuard<T>(fn: (XLSX: import('@/lib/sheetjs-loader').SheetJS) => T | Promise<T>): Promise<T> {
  const XLSX = await loadSheetJS();
  const prototypeKeysBefore = new Set<PropertyKey>(Reflect.ownKeys(Object.prototype));
  try {
    return await fn(XLSX);
  } finally {
    for (const key of Reflect.ownKeys(Object.prototype)) {
      if (!prototypeKeysBefore.has(key)) {
        Reflect.deleteProperty(Object.prototype, key);
      }
    }
  }
}

/**
 * Parse a workbook and return every worksheet as CSV.
 *
 * Each sheet is converted independently so that one malformed sheet cannot
 * take the others down with it: a sheet whose CSV conversion throws is
 * reported by name and the remaining sheets are still returned.
 */
async function readWorkbookSheets(buffer: ArrayBuffer): Promise<ParsedSheet[]> {
  return withParserGuard((XLSX) => {
    const workbook = XLSX.read(buffer, XLSX_READ_OPTIONS);

    if (workbook.SheetNames.length === 0) {
      throw new Error('Excel file has no sheets');
    }

    return workbook.SheetNames.map((name) => {
      const truncated = sheetRowCount(workbook.Sheets[name]) >= MAX_SHEET_ROWS;
      try {
        const sheet = workbook.Sheets[name];
        if (!sheet) {
          throw new Error('sheet is missing from the parsed workbook');
        }
        return { name, csv: XLSX.utils.sheet_to_csv(sheet), truncated };
      } catch (error) {
        // One bad sheet must not take the rest of the workbook down with it.
        return {
          name,
          csv: null,
          error: error instanceof Error ? error.message : 'Unknown error',
          truncated,
        };
      }
    });
  });
}

/**
 * List the worksheet names of an Excel file without converting any of them,
 * so the UI can offer a selection before anything is collected.
 */
export async function listWorkbookSheets(file: File): Promise<string[]> {
  return withParserGuard(async (XLSX) => {
    const workbook = XLSX.read(await file.arrayBuffer(), XLSX_READ_OPTIONS);
    if (workbook.SheetNames.length === 0) {
      throw new Error('Excel file has no sheets');
    }
    return workbook.SheetNames;
  });
}

/**
 * Parse a workbook and return its first sheet as CSV, for the legacy
 * single-file path. Multi-sheet workbooks get a notice naming the sheets
 * that were not analysed; the Dataset Manager path (addWorkbookSheets) lets
 * the user collect every sheet instead.
 */
async function readWorkbookAsCsv(buffer: ArrayBuffer): Promise<ParseResult> {
  const sheets = await readWorkbookSheets(buffer);
  const first = sheets[0]!; // readWorkbookSheets throws when there are none
  if (first.csv === null) {
    throw new Error(`Could not read sheet "${first.name}": ${first.error ?? 'Unknown error'}`);
  }

  // Only the first worksheet is analysed on this path. Saying nothing about
  // the others was the most likely source of a silently wrong answer in the
  // product: a user whose data sits on sheet 2 got a confident analysis of
  // sheet 1.
  const notices: string[] = [];
  if (sheets.length > 1) {
    const skipped = sheets.slice(1).map((s) => s.name);
    notices.push(
      `This workbook has ${sheets.length} worksheets. ` +
        `Only "${first.name}" was analysed. ` +
        `Not analysed: ${skipped.map((s) => `"${s}"`).join(', ')}. ` +
        `To analyse another sheet, save it as its own file and upload that, ` +
        `or use Link Datasets mode, where every worksheet can be collected.`
    );
  }
  if (first.truncated) {
    notices.push(
      `Worksheet "${first.name}" exceeded the ${MAX_SHEET_ROWS.toLocaleString()}-row ` +
        `limit and was truncated.`
    );
  }

  return { content: first.csv, notices };
}

/**
 * Header columns and data-row count of a CSV, honouring RFC 4180 quoting
 * ("a, b" is one field, "" is a literal quote, quoted fields may span lines)
 * so the columns offered for linking match what pandas reads in the worker.
 * Blank records after the header are not counted, as pandas skips them.
 */
function readCsvShape(content: string): { columns: string[]; rowCount: number } {
  let header: string[] | null = null;
  let fields: string[] = [];
  let field = '';
  let blank = true;
  let rowCount = 0;
  let inQuotes = false;

  const endRecord = () => {
    if (header === null) {
      fields.push(field);
      header = fields;
    } else if (!blank) {
      rowCount++;
    }
    fields = [];
    field = '';
    blank = true;
  };

  for (let i = 0; i < content.length; i++) {
    const c = content[i];
    if (inQuotes) {
      if (c === '"') {
        if (content[i + 1] === '"') {
          if (header === null) field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else if (header === null) {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
      blank = false;
    } else if (c === ',') {
      if (header === null) fields.push(field);
      field = '';
      blank = false;
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && content[i + 1] === '\n') i++;
      endRecord();
    } else {
      if (header === null) field += c;
      if (c !== ' ' && c !== '\t') blank = false;
    }
  }
  if (!blank || fields.length > 0 || field !== '') endRecord();

  const columns: string[] = (header ?? []).map((col: string) => col.trim());
  if (columns.length === 0 || columns.every((col) => col === '')) {
    throw new Error('File is empty');
  }
  return { columns, rowCount };
}

/**
 * Read an uploaded file as text, converting Excel workbooks to CSV.
 *
 * Single entry point on purpose - the hardening above must not end up applied to
 * only one of the two upload paths.
 */
async function readFileContent(file: File): Promise<ParseResult> {
  const ext = file.name.toLowerCase().split('.').pop();
  const isExcel = ext === 'xlsx' || ext === 'xls';

  if (isExcel) {
    // Read Excel and convert to CSV using SheetJS
    const buffer = await file.arrayBuffer();
    return readWorkbookAsCsv(buffer);
  }

  // XML is advertised in the uploader, the validator and the README, but no XML
  // parser exists anywhere in this codebase: the worker has zero XML handling,
  // so the raw "<?xml ...>" text was previously handed to pandas.read_csv. That
  // produced garbage columns presented as a successful analysis rather than an
  // error, which is the worst possible outcome for a product whose buyers are
  // auditors. Fail loudly until a real parser is implemented.
  if (ext === 'xml') {
    throw new Error(
      'XML is not supported yet. The format is listed in the interface by mistake: ' +
        'no XML parser is implemented, and parsing it as CSV would produce incorrect ' +
        'results rather than an error. Convert the file to CSV or Excel first.'
    );
  }

  // Read as text for CSV
  return { content: await file.text(), notices: [] };
}

// ═══════════════════════════════════════════════════════════════════════════
// WORKER MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════════

let worker: Worker | null = null;
let workerBlobUrl: string | null = null;
let workerWarmUpRequested = false;

function getWorker(): Worker {
  if (!worker) {
    // Security: the worker is the only thread that ever holds the plaintext
    // user data, so it must run under the document's Content-Security-Policy.
    // A worker loaded from an https: URL does NOT inherit the document policy -
    // its policy is built from the worker script's own response headers, and the
    // GitHub Pages deploy target cannot send any, so the worker would execute
    // unpoliced with fetch/XHR/WebSocket/importScripts open to every origin.
    // blob: is a local scheme, so a worker created from one inherits the
    // creating document's policy container (the CSP in index.html), which
    // denies every origin except the Pyodide CDN.
    if (!workerBlobUrl) {
      workerBlobUrl = URL.createObjectURL(
        new Blob([prismWorkerSource], { type: 'text/javascript' })
      );
    }
    // Use classic worker (not module) for importScripts compatibility
    worker = new Worker(workerBlobUrl, { type: 'classic' });
  }
  return worker;
}

/**
 * Create the worker and ask it to start loading Pyodide + pandas/numpy (~25 MB)
 * before any file is picked, so the download overlaps the user reading the
 * landing page instead of being serialised behind file validation and reading.
 *
 * Safe to call repeatedly: the worker's initializePyodide() is idempotent, and
 * no message handler is attached here so in-flight progress belongs to whichever
 * action runs next.
 */
export function warmUpWorker(): void {
  if (typeof Worker === 'undefined' || workerWarmUpRequested) {
    return;
  }
  workerWarmUpRequested = true;

  try {
    getWorker().postMessage({
      type: 'INIT',
      payload: {},
      timestamp: Date.now(),
      id: crypto.randomUUID(),
    });
  } catch (error) {
    // Warm-up is best effort - never block app start. getWorker() will create
    // the worker again on demand, which self-initialises on load.
    workerWarmUpRequested = false;
    console.error('Pyodide warm-up failed:', error);
  }
}

function terminateWorker(): void {
  if (worker) {
    worker.terminate();
    worker = null;
    workerWarmUpRequested = false;
  }
  if (workerBlobUrl) {
    URL.revokeObjectURL(workerBlobUrl);
    workerBlobUrl = null;
  }
}

// Start the Pyodide/pandas download as soon as the store module is imported.
warmUpWorker();

// ═══════════════════════════════════════════════════════════════════════════
// STORE DEFINITION
// ═══════════════════════════════════════════════════════════════════════════

export const usePrismStore = create<PrismState>((set, get) => ({
  ...initialState,

  /**
   * Handle file selection and validation
   */
  setFile: async (file: File) => {
    // Reset previous state
    set({
      file: {
        metadata: null,
        content: null,
        validationStatus: 'pending',
        validationError: null,
        notices: [],
      },
      processing: {
        status: 'validating',
        progress: 10,
        message: 'Validating file...',
        accessibleMessage: 'Validating your file. Please wait.',
      },
      error: null,
      results: {
        summary: null,
        recommendations: [],
        insights: [],
        chartConfigs: [],
      },
    });

    try {
      // Validate file
      const validationResult = await validateFile(file);

      if (!validationResult.isValid) {
        set({
          file: {
            metadata: null,
            content: null,
            validationStatus: 'invalid',
            validationError: validationResult.error || 'Invalid file',
            notices: [],
          },
          processing: initialProgress,
          error: {
            code: 'VALIDATION_ERROR',
            message: validationResult.error || 'File validation failed',
            recoverable: true,
          },
        });
        return;
      }

      // Read file content - convert Excel to CSV if needed
      const { content, notices } = await readFileContent(file);

      set({
        file: {
          metadata: validationResult.metadata!,
          content,
          validationStatus: 'valid',
          validationError: null,
          notices,
        },
        processing: {
          status: 'parsing',
          progress: 30,
          message: 'File validated successfully',
          accessibleMessage: `File ${validationResult.metadata!.name} validated. Ready for analysis.`,
        },
      });

      // Auto-start processing
      await get().processData();

    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      set({
        file: {
          ...get().file,
          validationStatus: 'invalid',
          validationError: message,
        },
        processing: initialProgress,
        error: {
          code: 'FILE_ERROR',
          message,
          recoverable: true,
        },
      });
    }
  },

  /**
   * Clear current file and results
   */
  clearFile: () => {
    terminateWorker();
    set({
      ...initialState,
      accessibility: get().accessibility, // Preserve accessibility settings
    });
  },

  /**
   * Process loaded file data through Pyodide
   */
  processData: async () => {
    const { file } = get();

    if (!file.content || !file.metadata) {
      set({
        error: {
          code: 'NO_DATA',
          message: 'No file loaded',
          recoverable: true,
        },
      });
      return;
    }

    set({
      processing: {
        status: 'analyzing',
        progress: 40,
        message: 'Starting analysis...',
        accessibleMessage: 'Starting data analysis. This may take a moment.',
      },
    });

    return new Promise<void>((resolve, reject) => {
      const prismWorker = getWorker();

      // Handle worker messages
      prismWorker.onmessage = (event: MessageEvent<WorkerMessage>) => {
        const { type, payload } = event.data;

        switch (type) {
          case 'PROGRESS':
            set({ processing: payload as ProcessingProgress });
            break;

          case 'RESULT': {
            const results = payload as WorkerResultPayload;
            set({
              results: {
                summary: results.summary,
                recommendations: results.recommendations,
                insights: results.insights,
                chartConfigs: results.chartData,
              },
              processing: {
                status: 'complete',
                progress: 100,
                message: 'Analysis complete!',
                accessibleMessage: `Analysis complete. Found ${results.insights.length} insights and ${results.recommendations.length} chart recommendations.`,
              },
            });
            resolve();
            break;
          }

          case 'ERROR':
            set({
              error: payload as ProcessingError,
              processing: {
                status: 'error',
                progress: 0,
                message: (payload as ProcessingError).message,
                accessibleMessage: `Error: ${(payload as ProcessingError).message}`,
              },
            });
            reject(new Error((payload as ProcessingError).message));
            break;
        }
      };

      // Handle worker errors
      prismWorker.onerror = (error) => {
        set({
          error: {
            code: 'WORKER_ERROR',
            message: error.message || 'Worker error',
            recoverable: true,
          },
          processing: {
            status: 'error',
            progress: 0,
            message: 'Analysis failed',
            accessibleMessage: 'Analysis failed. Please try again.',
          },
        });
        reject(error);
      };

      // Send data to worker
      prismWorker.postMessage({
        type: 'PROCESS_FILE',
        payload: {
          fileContent: file.content,
          fileType: file.metadata!.type,
          fileName: file.metadata!.name,
        },
        timestamp: Date.now(),
        id: crypto.randomUUID(),
      });
    });
  },

  /**
   * Update accessibility settings
   */
  setAccessibility: (settings: Partial<AccessibilitySettings>) => {
    set({
      accessibility: {
        ...get().accessibility,
        ...settings,
      },
    });
  },

  /**
   * Set active chart index
   */
  setActiveChart: (index: number) => {
    set({ activeChartIndex: index });
  },

  /**
   * Full reset to initial state
   */
  reset: () => {
    terminateWorker();
    set({
      ...initialState,
      accessibility: get().accessibility,
    });
  },

  // ═══════════════════════════════════════════════════════════════════════════
  // MULTI-DATASET ACTIONS
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Add a new dataset
   */
  addDataset: async (file: File) => {
    const validationResult = await validateFile(file);
    
    if (!validationResult.isValid) {
      set({
        error: {
          code: 'VALIDATION_ERROR',
          message: validationResult.error || 'File validation failed',
          recoverable: true,
        },
      });
      return;
    }

    // A throw here would escape to the dropzone's onDrop, leaving it stuck in
    // 'uploading' with no message. Report it the same way setFile does.
    try {
      // Read file content
      const { content, notices: parseNotices } = await readFileContent(file);
      if (parseNotices.length > 0) {
        set((state) => ({ file: { ...state.file, notices: parseNotices } }));
      }

      // Extract columns from the header record and count data records
      const { columns, rowCount } = readCsvShape(content);

      const newDataset: import('@/types').Dataset = {
        id: crypto.randomUUID(),
        name: file.name,
        metadata: validationResult.metadata!,
        content,
        columns,
        rowCount,
        isActive: get().datasets.length === 0, // First dataset is active
      };

      const currentDatasets = get().datasets;
      set({
        datasets: [...currentDatasets, newDataset],
        activeDatasetId: get().activeDatasetId || newDataset.id,
      });
    } catch (error) {
      set({
        error: {
          code: 'FILE_ERROR',
          message: error instanceof Error ? error.message : 'Unknown error',
          recoverable: true,
        },
      });
    }
  },

  /**
   * Validate an Excel file and list its worksheets so the user can choose
   * which ones to collect. Returns [] (and sets `error`) on failure.
   */
  prepareWorkbook: async (file: File) => {
    const validationResult = await validateFile(file);

    if (!validationResult.isValid) {
      set({
        error: {
          code: 'VALIDATION_ERROR',
          message: validationResult.error || 'File validation failed',
          recoverable: true,
        },
      });
      return [];
    }

    try {
      return await listWorkbookSheets(file);
    } catch (error) {
      set({
        error: {
          code: 'FILE_ERROR',
          message: error instanceof Error ? error.message : 'Unknown error',
          recoverable: true,
        },
      });
      return [];
    }
  },

  /**
   * Collect the selected worksheets of a workbook into the dataset list.
   *
   * Every sheet of the workbook ends up in `sheetOutcomes` exactly once:
   * collected (with its own header/row counts), failed (with the reason), or
   * not-selected. A sheet that fails to parse does not stop the others; only
   * when nothing at all could be collected is the overall `error` set.
   */
  addWorkbookSheets: async (file: File, sheetNames: string[]) => {
    const validationResult = await validateFile(file);

    if (!validationResult.isValid) {
      set({
        error: {
          code: 'VALIDATION_ERROR',
          message: validationResult.error || 'File validation failed',
          recoverable: true,
        },
      });
      return [];
    }

    try {
      const sheets = await readWorkbookSheets(await file.arrayBuffer());
      const selected = new Set(sheetNames);

      const outcomes: import('@/types').SheetOutcome[] = [];
      const newDatasets: import('@/types').Dataset[] = [];
      const truncationNotices: string[] = [];

      for (const sheet of sheets) {
        if (!selected.has(sheet.name)) {
          outcomes.push({ fileName: file.name, sheetName: sheet.name, status: 'not-selected' });
          continue;
        }

        if (sheet.csv === null) {
          outcomes.push({
            fileName: file.name,
            sheetName: sheet.name,
            status: 'failed',
            reason: sheet.error ?? 'Unknown error',
          });
          continue;
        }

        try {
          // Same RFC 4180 header/row accounting as every other upload path.
          const { columns, rowCount } = readCsvShape(sheet.csv);

          newDatasets.push({
            id: crypto.randomUUID(),
            name: `${file.name} · ${sheet.name}`,
            metadata: validationResult.metadata!,
            content: sheet.csv,
            columns,
            rowCount,
            isActive: get().datasets.length === 0 && newDatasets.length === 0,
          });

          const truncationReason = sheet.truncated
            ? `Worksheet exceeded the ${MAX_SHEET_ROWS.toLocaleString()}-row limit and was truncated.`
            : undefined;
          if (truncationReason) {
            truncationNotices.push(`"${sheet.name}" in ${file.name}: ${truncationReason}`);
          }
          outcomes.push({
            fileName: file.name,
            sheetName: sheet.name,
            status: 'collected',
            rowCount,
            columnCount: columns.length,
            ...(truncationReason ? { reason: truncationReason } : {}),
          });
        } catch (error) {
          outcomes.push({
            fileName: file.name,
            sheetName: sheet.name,
            status: 'failed',
            reason: error instanceof Error ? error.message : 'Unknown error',
          });
        }
      }

      set((state) => ({
        datasets: [...state.datasets, ...newDatasets],
        activeDatasetId: state.activeDatasetId ?? newDatasets[0]?.id ?? null,
        sheetOutcomes: [...state.sheetOutcomes, ...outcomes],
        ...(truncationNotices.length > 0
          ? { file: { ...state.file, notices: [...state.file.notices, ...truncationNotices] } }
          : {}),
      }));

      // All-or-nothing failure gets one explicit error rather than a silent
      // empty result; partial failure stays visible per-sheet in the outcomes.
      if (newDatasets.length === 0) {
        const failed = outcomes.filter((o) => o.status === 'failed');
        const message =
          failed.length > 0
            ? `No worksheets could be collected from ${file.name}: ` +
              failed.map((f) => `"${f.sheetName}" — ${f.reason}`).join('; ')
            : `No worksheets were selected in ${file.name}.`;
        set({
          error: { code: 'FILE_ERROR', message, recoverable: true },
        });
      }

      return outcomes;
    } catch (error) {
      set({
        error: {
          code: 'FILE_ERROR',
          message: error instanceof Error ? error.message : 'Unknown error',
          recoverable: true,
        },
      });
      return [];
    }
  },

  /**
   * Remove a dataset
   */
  removeDataset: (id: string) => {
    const filteredDatasets = get().datasets.filter(d => d.id !== id);
    const filteredLinks = get().datasetLinks.filter(
      l => l.leftDatasetId !== id && l.rightDatasetId !== id
    );
    
    set({
      datasets: filteredDatasets,
      datasetLinks: filteredLinks,
      activeDatasetId: filteredDatasets.length > 0 ? filteredDatasets[0]?.id ?? null : null,
    });
  },

  /**
   * Set active dataset
   */
  setActiveDataset: (id: string) => {
    set({
      datasets: get().datasets.map(d => ({
        ...d,
        isActive: d.id === id,
      })),
      activeDatasetId: id,
    });
  },

  /**
   * Add a link between two datasets
   */
  addDatasetLink: (link: Omit<import('@/types').DatasetLink, 'id'>) => {
    const newLink: import('@/types').DatasetLink = {
      ...link,
      id: crypto.randomUUID(),
    };
    set({
      datasetLinks: [...get().datasetLinks, newLink],
    });
  },

  /**
   * Remove a dataset link
   */
  removeDatasetLink: (id: string) => {
    set({
      datasetLinks: get().datasetLinks.filter(l => l.id !== id),
    });
  },

  /**
   * Process linked datasets (merge/join and analyze)
   */
  processLinkedDatasets: async () => {
    const { datasets, datasetLinks } = get();

    if (datasets.length === 0) {
      set({
        error: {
          code: 'NO_DATA',
          message: 'No datasets loaded',
          recoverable: true,
        },
      });
      return;
    }

    set({
      processing: {
        status: 'analyzing',
        progress: 20,
        message: 'Preparing datasets...',
        accessibleMessage: 'Preparing linked datasets for analysis.',
      },
    });

    return new Promise<void>((resolve, reject) => {
      const prismWorker = getWorker();

      prismWorker.onmessage = (event: MessageEvent<WorkerMessage>) => {
        const { type, payload } = event.data;

        switch (type) {
          case 'PROGRESS':
            set({ processing: payload as ProcessingProgress });
            break;

          case 'RESULT': {
            const results = payload as WorkerResultPayload;
            set({
              results: {
                summary: results.summary,
                recommendations: results.recommendations,
                insights: results.insights,
                chartConfigs: results.chartData,
              },
              processing: {
                status: 'complete',
                progress: 100,
                message: 'Analysis complete!',
                accessibleMessage: `Analysis complete. Found ${results.insights.length} insights.`,
              },
            });
            resolve();
            break;
          }

          case 'ERROR':
            set({
              error: payload as ProcessingError,
              processing: {
                status: 'error',
                progress: 0,
                message: (payload as ProcessingError).message,
                accessibleMessage: `Error: ${(payload as ProcessingError).message}`,
              },
            });
            reject(new Error((payload as ProcessingError).message));
            break;
        }
      };

      prismWorker.onerror = (error) => {
        set({
          error: {
            code: 'WORKER_ERROR',
            message: error.message || 'Worker error',
            recoverable: true,
          },
        });
        reject(error);
      };

      // Send datasets and links to worker
      prismWorker.postMessage({
        type: 'PROCESS_LINKED_DATASETS',
        payload: {
          datasets: datasets.map(d => ({
            id: d.id,
            name: d.name,
            content: d.content,
            columns: d.columns,
          })),
          links: datasetLinks,
        },
        timestamp: Date.now(),
        id: crypto.randomUUID(),
      });
    });
  },

  /**
   * Run custom analysis (statistical tests, visualizations, preprocessing)
   */
  runCustomAnalysis: async (config: import('@/types').CustomAnalysisConfig): Promise<import('@/types').CustomAnalysisResult> => {
    const { file, datasets, activeDatasetId } = get();
    
    // Get current data content
    let dataContent = file.content;
    if (!dataContent && datasets.length > 0) {
      const activeDataset = datasets.find(d => d.id === activeDatasetId) || datasets[0];
      dataContent = activeDataset?.content || null;
    }
    
    if (!dataContent) {
      const result: import('@/types').CustomAnalysisResult = {
        type: config.type,
        success: false,
        error: 'No data available for analysis',
      };
      set({ customAnalysisResults: result });
      return result;
    }

    set({
      processing: {
        status: 'analyzing',
        progress: 30,
        message: `Running ${config.type}...`,
        accessibleMessage: `Running custom ${config.type} analysis.`,
      },
    });

    return new Promise((resolve, reject) => {
      const prismWorker = getWorker();

      prismWorker.onmessage = (event: MessageEvent<WorkerMessage>) => {
        const { type, payload } = event.data;

        switch (type) {
          case 'PROGRESS':
            set({ processing: payload as ProcessingProgress });
            break;

          case 'CUSTOM_ANALYSIS_RESULT': {
            const result = payload as import('@/types').CustomAnalysisResult;
            set({
              customAnalysisResults: result,
              processing: {
                status: 'complete',
                progress: 100,
                message: 'Analysis complete!',
                accessibleMessage: 'Custom analysis completed successfully.',
              },
            });
            resolve(result);
            break;
          }

          case 'ERROR':
            const errorResult: import('@/types').CustomAnalysisResult = {
              type: config.type,
              success: false,
              error: (payload as ProcessingError).message,
            };
            set({
              customAnalysisResults: errorResult,
              processing: {
                status: 'error',
                progress: 0,
                message: (payload as ProcessingError).message,
                accessibleMessage: `Error: ${(payload as ProcessingError).message}`,
              },
            });
            resolve(errorResult);
            break;
        }
      };

      prismWorker.onerror = (error) => {
        const errorResult: import('@/types').CustomAnalysisResult = {
          type: config.type,
          success: false,
          error: error.message || 'Worker error',
        };
        set({ customAnalysisResults: errorResult });
        reject(error);
      };

      // Send analysis request to worker
      prismWorker.postMessage({
        type: 'CUSTOM_ANALYSIS',
        payload: {
          config,
          dataContent,
        },
        timestamp: Date.now(),
        id: crypto.randomUUID(),
      });
    });
  },
}));

export default usePrismStore;
