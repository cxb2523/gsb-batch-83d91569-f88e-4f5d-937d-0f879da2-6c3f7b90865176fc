/**
 * @vitest-environment jsdom
 *
 * Tests for multi-worksheet workbook collection in prismStore.
 *
 * The old pipeline converted only the first worksheet of a workbook to CSV and
 * silently dropped the rest. These tests pin down the replacement behaviour:
 *
 *  1. A multi-sheet workbook collects every selected sheet as its own dataset,
 *     named "file · sheet", with columns/rows counted from that sheet's header.
 *  2. A sheet the user did not select is reported as 'not-selected' and never
 *     becomes a dataset.
 *  3. One sheet failing to parse does not stop the other sheets.
 *  4. When every selected sheet fails, the store raises one explicit overall
 *     error instead of returning an empty result.
 *  5. A sheet that hits the 100,000-row read cap is collected but flagged as
 *     truncated, and the truncation surfaces in the file notices.
 *
 * The SheetJS parser is faked via window.XLSX (the seam loadSheetJS already
 * uses), so the tests construct parse results directly instead of building
 * real workbooks. The RFC 4180 header/row accounting under test is the real
 * readCsvShape in the store.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { usePrismStore } from '@/stores/prismStore';
import type { SheetJS } from '@/lib/sheetjs-loader';

interface FakeSheet {
  csv: string;
  '!ref'?: string;
}

/** Install a fake SheetJS whose read() returns a workbook with the given sheets. */
function installFakeWorkbook(sheets: Record<string, FakeSheet>): void {
  window.XLSX = {
    read: () => ({
      SheetNames: Object.keys(sheets),
      Sheets: sheets as Record<string, unknown>,
    }),
    utils: {
      sheet_to_csv: (sheet: unknown) => (sheet as FakeSheet).csv,
    },
  } as SheetJS;
}

/** Minimal .xlsx upload: real PK magic bytes and >= 10 bytes so validateFile passes. */
function workbookFile(name = 'book.xlsx'): File {
  const bytes = new Uint8Array([
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x08, 0x00, 0x00, 0x00,
  ]);
  return new File([bytes], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}

const pristine = usePrismStore.getState();

beforeEach(() => {
  usePrismStore.setState({
    datasets: [],
    datasetLinks: [],
    activeDatasetId: null,
    sheetOutcomes: [],
    error: null,
    file: { ...pristine.file, notices: [] },
  });
});

afterEach(() => {
  delete window.XLSX;
});

describe('prepareWorkbook', () => {
  it('lists every worksheet of a multi-sheet workbook for selection', async () => {
    installFakeWorkbook({
      Alpha: { csv: 'a\n1\n' },
      Beta: { csv: 'b\n2\n' },
      Gamma: { csv: 'c\n3\n' },
    });

    const sheets = await usePrismStore.getState().prepareWorkbook(workbookFile());

    expect(sheets).toEqual(['Alpha', 'Beta', 'Gamma']);
    expect(usePrismStore.getState().error).toBeNull();
  });
});

describe('addWorkbookSheets', () => {
  it('collects every selected sheet as its own dataset with its own shape', async () => {
    installFakeWorkbook({
      Alpha: { csv: 'a,b\n1,2\n3,4\n' },
      Beta: { csv: 'name\n"x"\n' },
      Gamma: { csv: 'p,q,r\n1,2,3\n' },
    });
    const file = workbookFile();

    const sheets = await usePrismStore.getState().prepareWorkbook(file);
    // Default selection in the UI is "all sheets"; pass them all through.
    const outcomes = await usePrismStore.getState().addWorkbookSheets(file, sheets);

    const state = usePrismStore.getState();
    expect(state.error).toBeNull();
    expect(state.datasets.map((d) => d.name)).toEqual([
      'book.xlsx · Alpha',
      'book.xlsx · Beta',
      'book.xlsx · Gamma',
    ]);
    // Columns and row counts come from each sheet's own header, not the first sheet's.
    expect(state.datasets[0]?.columns).toEqual(['a', 'b']);
    expect(state.datasets[0]?.rowCount).toBe(2);
    expect(state.datasets[1]?.columns).toEqual(['name']);
    expect(state.datasets[1]?.rowCount).toBe(1);
    expect(state.datasets[2]?.columns).toEqual(['p', 'q', 'r']);
    expect(state.datasets[2]?.rowCount).toBe(1);

    expect(outcomes.map((o) => o.status)).toEqual(['collected', 'collected', 'collected']);
    expect(state.sheetOutcomes.map((o) => o.sheetName)).toEqual(['Alpha', 'Beta', 'Gamma']);
    expect(state.sheetOutcomes[0]).toMatchObject({
      fileName: 'book.xlsx',
      status: 'collected',
      rowCount: 2,
      columnCount: 2,
    });
  });

  it('marks unchecked sheets as not-selected and keeps them out of the datasets', async () => {
    installFakeWorkbook({
      Keep: { csv: 'a\n1\n' },
      Skip: { csv: 'b\n2\n' },
      AlsoKeep: { csv: 'c\n3\n' },
    });

    const outcomes = await usePrismStore
      .getState()
      .addWorkbookSheets(workbookFile(), ['Keep', 'AlsoKeep']);

    const state = usePrismStore.getState();
    expect(state.error).toBeNull();
    expect(state.datasets.map((d) => d.name)).toEqual([
      'book.xlsx · Keep',
      'book.xlsx · AlsoKeep',
    ]);
    // The unselected sheet is still accounted for, in workbook order.
    expect(state.sheetOutcomes.map((o) => [o.sheetName, o.status])).toEqual([
      ['Keep', 'collected'],
      ['Skip', 'not-selected'],
      ['AlsoKeep', 'collected'],
    ]);
    expect(outcomes.find((o) => o.sheetName === 'Skip')).toMatchObject({
      fileName: 'book.xlsx',
      status: 'not-selected',
    });
  });

  it('collects the remaining sheets when one sheet fails to parse', async () => {
    installFakeWorkbook({
      Good: { csv: 'a,b\n1,2\n' },
      Empty: { csv: '' }, // readCsvShape: no header record -> "File is empty"
      AlsoGood: { csv: 'x\n9\n' },
    });

    const outcomes = await usePrismStore
      .getState()
      .addWorkbookSheets(workbookFile(), ['Good', 'Empty', 'AlsoGood']);

    const state = usePrismStore.getState();
    // Partial failure is reported per sheet, not as an overall error.
    expect(state.error).toBeNull();
    expect(state.datasets.map((d) => d.name)).toEqual([
      'book.xlsx · Good',
      'book.xlsx · AlsoGood',
    ]);
    const failed = outcomes.find((o) => o.sheetName === 'Empty');
    expect(failed?.status).toBe('failed');
    expect(failed?.reason).toContain('empty');
    expect(state.sheetOutcomes.map((o) => o.status)).toEqual([
      'collected',
      'failed',
      'collected',
    ]);
  });

  it('reports a sheet whose CSV conversion itself throws as failed, not fatal', async () => {
    window.XLSX = {
      read: () => ({
        SheetNames: ['Broken', 'Fine'],
        Sheets: { Broken: { csv: '' }, Fine: { csv: 'a\n1\n' } },
      }),
      utils: {
        sheet_to_csv: (sheet: unknown) => {
          const csv = (sheet as FakeSheet).csv;
          if (csv === '') throw new Error('malformed sheet XML');
          return csv;
        },
      },
    } as SheetJS;

    const outcomes = await usePrismStore
      .getState()
      .addWorkbookSheets(workbookFile(), ['Broken', 'Fine']);

    const state = usePrismStore.getState();
    expect(state.error).toBeNull();
    expect(state.datasets.map((d) => d.name)).toEqual(['book.xlsx · Fine']);
    expect(outcomes.find((o) => o.sheetName === 'Broken')).toMatchObject({
      status: 'failed',
      reason: 'malformed sheet XML',
    });
  });

  it('sets one explicit overall error when every selected sheet fails', async () => {
    installFakeWorkbook({
      Empty1: { csv: '' },
      Empty2: { csv: '' },
    });

    const outcomes = await usePrismStore
      .getState()
      .addWorkbookSheets(workbookFile(), ['Empty1', 'Empty2']);

    const state = usePrismStore.getState();
    expect(state.datasets).toHaveLength(0);
    expect(outcomes.every((o) => o.status === 'failed')).toBe(true);
    expect(state.error).toMatchObject({ code: 'FILE_ERROR', recoverable: true });
    expect(state.error?.message).toContain('book.xlsx');
    expect(state.error?.message).toContain('Empty1');
    expect(state.error?.message).toContain('Empty2');
  });

  it('flags sheets that hit the 100,000-row read cap as truncated', async () => {
    installFakeWorkbook({
      Huge: { csv: 'a,b\n1,2\n', '!ref': 'A1:B100000' },
      Small: { csv: 'a\n1\n', '!ref': 'A1:A2' },
    });

    const outcomes = await usePrismStore
      .getState()
      .addWorkbookSheets(workbookFile(), ['Huge', 'Small']);

    const huge = outcomes.find((o) => o.sheetName === 'Huge');
    expect(huge?.status).toBe('collected');
    expect(huge?.reason).toContain('truncated');
    expect(huge?.reason).toContain('100,000');
    expect(outcomes.find((o) => o.sheetName === 'Small')?.reason).toBeUndefined();
    // The truncation also surfaces in the file notices shown next to results.
    const notices = usePrismStore.getState().file.notices;
    expect(notices.some((n) => n.includes('Huge') && n.includes('truncated'))).toBe(true);
  });
});
