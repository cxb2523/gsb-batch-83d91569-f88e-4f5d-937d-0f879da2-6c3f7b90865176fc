import { LitElement, css, unsafeCSS } from 'lit';
import { PANEL_IMAGE_DATA_URI } from './panel-image';
import { htmlFromTpl } from './template-utils';
import cardStyles from './templates/solar-panel-grid-card.css';
import cardRenderTpl from './templates/solar-panel-grid-card-render.tpl';
import cardTopControlsTpl from './templates/solar-panel-grid-card-top-controls.tpl';
import cardEnergyToggleTpl from './templates/solar-panel-grid-card-energy-toggle.tpl';
import cardHistoryMetaTpl from './templates/solar-panel-grid-card-history-meta.tpl';
import cardHistoryStatusTpl from './templates/solar-panel-grid-card-history-status.tpl';
import cardHistoryErrorTpl from './templates/solar-panel-grid-card-history-error.tpl';
import cardCanvasTpl from './templates/solar-panel-grid-card-canvas.tpl';
import cardBackgroundImageTpl from './templates/solar-panel-grid-card-background-image.tpl';
import cardPanelTpl from './templates/solar-panel-grid-card-panel.tpl';
import cardPanelValueTpl from './templates/solar-panel-grid-card-panel-value.tpl';
import cardPanelStatusTpl from './templates/solar-panel-grid-card-panel-status.tpl';
import cardPanelMissingTpl from './templates/solar-panel-grid-card-panel-missing.tpl';
import cardPanelOutcomesTpl from './templates/solar-panel-grid-card-panel-outcomes.tpl';
import cardPanelErrorTpl from './templates/solar-panel-grid-card-panel-error.tpl';

interface SolarPanelConfig {
  entity: string;
  entity_energy?: string;      // secondary entity for energy (kWh)
  x: number;
  y: number;
  name?: string;              // optional display name (defaults to last 4 chars of entity_id)
  rotation?: number;           // degrees, clockwise
  max_daily_production?: number; // kWh
  max_production?: number; // W
}

interface SolarPanelGridCardConfig {
  type: string;
  panels: SolarPanelConfig[];
  grid_size?: number; // pixels for snap-to-grid
  panel_width?: number;
  panel_height?: number;
  canvas_width?: number;       // optional fixed canvas width (px)
  canvas_height?: number;      // optional fixed canvas height (px)
  canvas_rotation?: number;    // degrees, clockwise
  background_image?: string;
  background_opacity?: number;
  persist_view_state?: boolean; // persist W/kWh toggle state in localStorage
}

// default values used throughout the card
const DEFAULT_GRID_SIZE = 10;
const DEFAULT_PANEL_WIDTH = 80;          // px, 1:1.8 aspect ratio
const DEFAULT_PANEL_HEIGHT = 144;        // px, 1:1.8 aspect ratio
const DEFAULT_CONTAINER_WIDTH = 1200;    // px workspace
const DEFAULT_CONTAINER_HEIGHT = 1200;   // px workspace

interface HassEntity {
  entity_id: string;
  state: string;
  attributes: {
    unit_of_measurement?: string;
    friendly_name?: string;
    [key: string]: any;
  };
}

interface Hass {
  states: Record<string, HassEntity>;
  callService: (domain: string, service: string, data?: any) => Promise<void>;
  callApi?: <T = any>(method: string, path: string, parameters?: Record<string, any>) => Promise<T>;
}

/**
 * Per-entity outcome of a historical fetch.  Each configured entity
 * (a panel's power entity and its optional energy entity) gets exactly one
 * of these, independently from all other entities.
 */
type HistoryOutcome = 'record' | 'empty' | 'error' | 'invalid';

interface HistoryEntityResult {
  entityId: string;
  outcome: HistoryOutcome;
  entity?: HassEntity;
  message?: string;
}

interface HistorySnapshot {
  /** Local date + minute label of the last successful fetch. */
  label: string;
}

/** A value kept for display, together with the snapshot it came from. */
interface HistoryValueEntry {
  entity: HassEntity;
  label: string;
}

const HISTORY_OUTCOME_LABELS: Record<HistoryOutcome, string> = {
  record: 'Loaded',
  empty: 'No record',
  error: 'Failed',
  invalid: 'Bad data',
};

// Helper function to convert HSL to RGB
function hslToRgb(h: number, s: number, l: number): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0,
    g = 0,
    b = 0;

  if (h >= 0 && h < 60) {
    r = c;
    g = x;
    b = 0;
  } else if (h >= 60 && h < 120) {
    r = x;
    g = c;
    b = 0;
  } else if (h >= 120 && h < 180) {
    r = 0;
    g = c;
    b = x;
  } else if (h >= 180 && h < 240) {
    r = 0;
    g = x;
    b = c;
  } else if (h >= 240 && h < 300) {
    r = x;
    g = 0;
    b = c;
  } else if (h >= 300 && h < 360) {
    r = c;
    g = 0;
    b = x;
  }

  const rr = Math.round((r + m) * 255)
    .toString(16)
    .padStart(2, '0');
  const gg = Math.round((g + m) * 255)
    .toString(16)
    .padStart(2, '0');
  const bb = Math.round((b + m) * 255)
    .toString(16)
    .padStart(2, '0');

  return `#${rr}${gg}${bb}`;
}

export class SolarPanelGridCard extends LitElement {
  private static readonly VIEW_STATE_STORAGE_KEY = 'solar-panel-card-show-energy';

  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _showEnergy: { state: true },
      _scale: { state: true },
      _selectedDate: { state: true },
      _selectedMinute: { state: true },
      _historyLoading: { state: true },
      _historyError: { state: true },
      _viewZoom: { state: true },
      _viewPanX: { state: true },
      _viewPanY: { state: true },
    };
  }

  hass!: Hass;
  config!: SolarPanelGridCardConfig;
  private _showEnergy = false;
  private _scale = 1;
  private _selectedDate = '';
  private _selectedMinute = 0;
  private _historyLoading = false;
  private _historyError = '';
  private _viewZoom = 1;
  private _viewPanX = 0;
  private _viewPanY = 0;
  private _resizeObserver: ResizeObserver | undefined = undefined;
  private _historySnapshot: HistorySnapshot | undefined = undefined;
  private _historyDebounceTimer: number | undefined;
  private _historyRequestToken = 0;
  /** Per-entity outcomes for the most recent completed request. */
  private _historyResults: Map<string, HistoryEntityResult> = new Map();
  /** Values to display for the current selection (record or carried over). */
  private _historyValues: Map<string, HistoryValueEntry> = new Map();
  private _activePointers: Map<number, { x: number; y: number }> = new Map();
  private _isViewportPanning = false;
  private _panStartPoint = { x: 0, y: 0 };
  private _panStartOffset = { x: 0, y: 0 };
  private _pinchLastDistance = 0;
  private _pinchLastMidpoint: { x: number; y: number } | null = null;
  private _suppressPanelClick = false;
  
  private panels: Map<
    string,
    { config: SolarPanelConfig; entity?: HassEntity; entityEnergy?: HassEntity }
  > = new Map();
  private draggedPanel: string | null = null;
  private dragOffset = { x: 0, y: 0 };
  private panelImage: string = PANEL_IMAGE_DATA_URI;
  private containerWidth = DEFAULT_CONTAINER_WIDTH;
  private containerHeight = DEFAULT_CONTAINER_HEIGHT;
  private gridSize = DEFAULT_GRID_SIZE;
  private panelWidth = DEFAULT_PANEL_WIDTH;
  private panelHeight = DEFAULT_PANEL_HEIGHT;

  // Determine whether this card is being rendered inside the editor's
  // preview pane (i.e. the configuration dialog).  The preview wrapper
  // may provide either a `preview` attribute or the `element-preview`
  // CSS class on one of the ancestors, which can be inside a shadow root.
  private get isEditorPreview(): boolean {
    let node: any = this;
    while (node) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        const el = node as HTMLElement;
        if (el.hasAttribute('preview') || el.classList.contains('element-preview')) {
          return true;
        }
      }
      if (node instanceof ShadowRoot) {
        node = node.host;
      } else {
        node = node.parentNode;
      }
    }
    return false;
  }


  // Calculate background color based on production
  private getProductionColor(value: number, max: number): string {
    if (!max || max === 0) return '#000000'; // black for 0%

    const percentage = Math.min(Math.max(value / max, 0), 1);

    // Hue range: 240 (dark blue) to 180 (light blue)
    // As percentage increases, we go from dark blue (high saturation, low lightness)
    // to light blue (medium saturation, high lightness)
    const hue = 240 - percentage * 60; // 240 to 180
    const saturation = 0.6 + percentage * 0.4; // 60% to 100%
    const lightness = 0.2 + percentage * 0.5; // 20% to 70%

    return hslToRgb(hue, saturation, lightness);
  }

  static getConfigElement() {
    return document.createElement('solar-panel-grid-card-editor');
  }

  static getConfigForm() {
    // Providing both for compatibility, but getConfigElement takes precedence
    return null;
  }

  static getStubConfig() {
    return {
      type: 'custom:solar-panel-grid-card',
      grid_size: DEFAULT_GRID_SIZE,
      panel_width: DEFAULT_PANEL_WIDTH,
      panel_height: DEFAULT_PANEL_HEIGHT,
      panels: [
        {
          entity: 'sensor.solar_panel_1',
          name: 'Pnl1',
          x: 0,
          y: 0,
          max_daily_production: 5.5,
          max_production: 400,
        },
      ],
    };
  }

  setConfig(config: SolarPanelGridCardConfig) {
    // Initialize with defaults if panels aren't configured
    if (!config.panels || !Array.isArray(config.panels)) {
      config.panels = [];
    }

    this.config = config;
    this.gridSize = config.grid_size || DEFAULT_GRID_SIZE;
    this.panelWidth = config.panel_width || DEFAULT_PANEL_WIDTH;
    this.panelHeight = config.panel_height || DEFAULT_PANEL_HEIGHT;
    this._showEnergy = this._loadViewState();
    this._initializeTimeSelection();

    this.panels.clear();
    config.panels.forEach((panelConfig) => {
      this.panels.set(panelConfig.entity, {
        config: panelConfig,
        entity: undefined,
      });
    });
  }

  private _loadViewState(): boolean {
    if (!this.config?.persist_view_state) {
      return false;
    }

    try {
      return localStorage.getItem(SolarPanelGridCard.VIEW_STATE_STORAGE_KEY) === 'true';
    } catch {
      return false;
    }
  }

  private _saveViewState(value: boolean): void {
    if (!this.config?.persist_view_state) {
      return;
    }

    try {
      localStorage.setItem(SolarPanelGridCard.VIEW_STATE_STORAGE_KEY, String(value));
    } catch {
      // Ignore localStorage errors (e.g. private mode / restricted browser context)
    }
  }

  update(changedProperties: Map<string | number | symbol, unknown>) {
    super.update(changedProperties);

    if (changedProperties.has('config')) {
      // rebuild panels map whenever config changes
      this.panels.clear();
      if (this.config?.panels) {
        this.config.panels.forEach((panelConfig) => {
          this.panels.set(panelConfig.entity, {
            config: panelConfig,
            entity: this.hass?.states[panelConfig.entity],
            entityEnergy: panelConfig.entity_energy ? this.hass?.states[panelConfig.entity_energy] : undefined,
          });
        });
      }
    }

    if (changedProperties.has('hass') && this.hass) {
      // Update just the entity references when hass updates
      this.panels.forEach((panel, entity) => {
        panel.entity = this.hass.states[entity];
        if (panel.config.entity_energy) {
          panel.entityEnergy = this.hass.states[panel.config.entity_energy];
        }
      });

      // Keep selection on current minute by default while card remains in live view.
      if (this._isTodaySelected()) {
        const now = new Date();
        const nowMinutes = now.getHours() * 60 + now.getMinutes();
        if (Math.abs(this._selectedMinute - nowMinutes) <= 1) {
          this._selectedMinute = nowMinutes;
        }
      }
    }

    if (changedProperties.has('_scale') || changedProperties.has('config')) {
      this._applyPan(this._viewPanX, this._viewPanY);
    }

    // Do not auto-fetch history on frequent hass/config updates.
    // History requests should only happen from explicit user timeline actions
    // (date change, time slider change, or "Now" button).
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
    }
    if (this._historyDebounceTimer !== undefined) {
      window.clearTimeout(this._historyDebounceTimer);
      this._historyDebounceTimer = undefined;
    }
  }

  private _initializeTimeSelection(): void {
    if (this._selectedDate) {
      return;
    }

    const now = new Date();
    this._selectedDate = this._toDateInputValue(now);
    this._selectedMinute = now.getHours() * 60 + now.getMinutes();
  }

  private _toDateInputValue(date: Date): string {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  private _minutesToLabel(totalMinutes: number): string {
    const minutes = Math.max(0, Math.min(1439, totalMinutes));
    const h = String(Math.floor(minutes / 60)).padStart(2, '0');
    const m = String(minutes % 60).padStart(2, '0');
    return `${h}:${m}`;
  }

  private _isTodaySelected(): boolean {
    if (!this._selectedDate) return false;
    return this._selectedDate === this._toDateInputValue(new Date());
  }

  private _getSelectedDateTime(): Date {
    const [y, m, d] = this._selectedDate.split('-').map((n) => Number(n));
    const local = new Date(y, (m || 1) - 1, d || 1, 0, 0, 0, 0);
    local.setMinutes(Math.max(0, Math.min(1439, this._selectedMinute)));
    return local;
  }

  private _getHistoryEntityIds(): string[] {
    const allIds = new Set<string>();
    this.panels.forEach((panel) => {
      allIds.add(panel.config.entity);
      if (panel.config.entity_energy) {
        allIds.add(panel.config.entity_energy);
      }
    });
    return Array.from(allIds).filter((entityId) => !!entityId && !entityId.endsWith('.'));
  }

  private _scheduleHistoryFetch(delayMs = 150): void {
    if (!this.hass || !this.config) {
      return;
    }

    // Invalidate any in-flight request immediately: a response that arrives
    // after the selection changed must never be rendered.
    const requestToken = ++this._historyRequestToken;

    if (this._historyDebounceTimer !== undefined) {
      window.clearTimeout(this._historyDebounceTimer);
    }

    this._historyDebounceTimer = window.setTimeout(() => {
      this._historyDebounceTimer = undefined;
      void this._fetchHistoricalSnapshot(requestToken);
    }, delayMs);
  }

  private async _fetchHistoricalSnapshot(requestToken?: number): Promise<void> {
    const token = requestToken ?? ++this._historyRequestToken;
    if (token !== this._historyRequestToken) {
      // A newer selection superseded this request before it even started.
      return;
    }

    if (!this._selectedDate) {
      this._resetHistoryState();
      this.requestUpdate();
      return;
    }

    const entityIds = this._getHistoryEntityIds();
    if (entityIds.length === 0) {
      this._resetHistoryState();
      this.requestUpdate();
      return;
    }

    if (!this.hass?.callApi) {
      // The history API is not available yet. Keep any previously rendered
      // snapshot and explain why the selection could not be refreshed.
      this._historyLoading = false;
      this._historyError = `Unable to load history for ${this._describeSelection()}: `
        + 'the history API is unavailable.'
        + (this._historySnapshot
          ? ` Showing last successful snapshot from ${this._historySnapshot.label}.`
          : ' No previous successful snapshot to show.');
      this.requestUpdate();
      return;
    }

    this._historyLoading = true;
    this._historyError = '';
    this.requestUpdate();

    const endTime = this._getSelectedDateTime();
    const startTime = new Date(endTime);
    startTime.setHours(0, 0, 0, 0);
    const selectionLabel = `${endTime.toLocaleDateString()} ${this._minutesToLabel(this._selectedMinute)}`;

    // One request per configured entity (power and optional energy), so each
    // entity gets its own outcome instead of sharing the fate of a single
    // batched response.
    const entityResults = await Promise.all(
      entityIds.map((entityId) => this._fetchEntityHistory(entityId, startTime, endTime))
    );

    if (token !== this._historyRequestToken) {
      // Stale response: the user picked another date/time meanwhile.
      return;
    }

    this._historyLoading = false;

    const results = new Map<string, HistoryEntityResult>();
    entityResults.forEach((result) => results.set(result.entityId, result));
    this._historyResults = results;

    // Entities that resolved (record or empty) are authoritative for the new
    // selection. Entities whose request failed or returned junk keep the value
    // from the last successful snapshot, if any.
    const values = new Map<string, HistoryValueEntry>();
    entityResults.forEach((result) => {
      if (result.outcome === 'record' && result.entity) {
        values.set(result.entityId, { entity: result.entity, label: selectionLabel });
      } else if (result.outcome === 'error' || result.outcome === 'invalid') {
        const previous = this._historyValues.get(result.entityId);
        if (previous) {
          values.set(result.entityId, previous);
        }
      }
    });

    const resolvedCount = entityResults.filter(
      (result) => result.outcome === 'record' || result.outcome === 'empty'
    ).length;

    this._historyValues = values;

    if (resolvedCount === 0) {
      // Nothing at all could be resolved: keep the last successful snapshot
      // (values and label) and surface the reason plus the snapshot time.
      this._historyError = this._buildHistoryFailureMessage(
        selectionLabel,
        entityResults,
        this._historySnapshot?.label
      );
      console.error('[SolarPanelGridCard] History fetch failed:', entityResults);
      this.requestUpdate();
      return;
    }

    this._historySnapshot = { label: selectionLabel };
    this._historyError = '';
    this.requestUpdate();
  }

  private _resetHistoryState(): void {
    this._historySnapshot = undefined;
    this._historyResults = new Map();
    this._historyValues = new Map();
    this._historyError = '';
    this._historyLoading = false;
  }

  private async _fetchEntityHistory(
    entityId: string,
    startTime: Date,
    endTime: Date
  ): Promise<HistoryEntityResult> {
    const callApi = this.hass?.callApi;
    if (!callApi) {
      return { entityId, outcome: 'error', message: 'History API is unavailable.' };
    }

    const path = `history/period/${encodeURIComponent(startTime.toISOString())}`
      + `?filter_entity_id=${encodeURIComponent(entityId)}`
      + `&end_time=${encodeURIComponent(endTime.toISOString())}`;

    let response: unknown;
    try {
      response = await callApi('GET', path);
    } catch (err) {
      const message = err instanceof Error
        ? err.message
        : (typeof err === 'string' && err ? err : 'request failed');
      return { entityId, outcome: 'error', message };
    }

    return this._parseEntityHistory(entityId, response);
  }

  /**
   * Classify what the history/period endpoint returned for a single entity.
   * Anything that is not a list, a list without records, or a list whose
   * latest entry cannot be understood is reported separately from a request
   * error so the user can tell "no production that day" from "fetch failed".
   */
  private _parseEntityHistory(entityId: string, response: unknown): HistoryEntityResult {
    if (!Array.isArray(response)) {
      return {
        entityId,
        outcome: 'invalid',
        message: 'History response was not a list.',
      };
    }

    if (response.length === 0) {
      return { entityId, outcome: 'empty' };
    }

    const entries = response as unknown[];
    let records: unknown[] | undefined;

    if (entries.every((entry) => Array.isArray(entry))) {
      // Home Assistant returns one list of records per requested entity.
      const lists = entries as unknown[][];
      const nonEmptyLists = lists.filter((list) => list.length > 0);
      if (nonEmptyLists.length === 0) {
        return { entityId, outcome: 'empty' };
      }

      const matchingList = nonEmptyLists.find((list) => {
        const last = list[list.length - 1];
        return this._isHistoryRecord(last) && (last as any).entity_id === entityId;
      });
      records = matchingList || nonEmptyLists[0];
    } else if (entries.every((entry) => this._isHistoryRecord(entry))) {
      // Tolerate a flat list of records for the filtered entity.
      records = entries;
    } else {
      return {
        entityId,
        outcome: 'invalid',
        message: 'History response did not contain recognizable records.',
      };
    }

    const latest = records[records.length - 1];
    if (!this._isHistoryRecord(latest) || latest.state === null) {
      return {
        entityId,
        outcome: 'invalid',
        message: 'Latest history record could not be interpreted.',
      };
    }

    const liveEntity = this.hass?.states?.[entityId];
    return {
      entityId,
      outcome: 'record',
      entity: {
        entity_id: entityId,
        state: String(latest.state),
        attributes: {
          ...(liveEntity?.attributes || {}),
          ...(this._isPlainObject(latest.attributes) ? latest.attributes : {}),
        },
      },
    };
  }

  private _isHistoryRecord(value: unknown): value is Record<string, any> {
    return this._isPlainObject(value) && 'state' in (value as Record<string, any>);
  }

  private _isPlainObject(value: unknown): value is Record<string, any> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  private _buildHistoryFailureMessage(
    selectionLabel: string,
    results: HistoryEntityResult[],
    snapshotLabel?: string
  ): string {
    const errorResults = results.filter((result) => result.outcome === 'error');
    const invalidResults = results.filter((result) => result.outcome === 'invalid');
    const reasons: string[] = [];

    if (errorResults.length > 0) {
      const detail = errorResults.find((result) => result.message)?.message;
      const count = `${errorResults.length} request${errorResults.length === 1 ? '' : 's'} failed`;
      reasons.push(detail ? `${count} (${detail})` : count);
    }
    if (invalidResults.length > 0) {
      reasons.push(
        `${invalidResults.length} returned unrecognized data`
      );
    }

    const reasonText = reasons.join('; ') || 'history request failed';
    const base = `Unable to load history for ${selectionLabel}: ${reasonText}.`;
    return snapshotLabel
      ? `${base} Showing last successful snapshot from ${snapshotLabel}.`
      : `${base} No previous successful snapshot to show.`;
  }

  private _getDisplayEntityInfo(entityId?: string): {
    entity?: HassEntity;
    outcome?: HistoryOutcome;
    valueLabel?: string;
  } {
    if (!entityId) {
      return {};
    }

    const result = this._historyResults.get(entityId);
    const entry = this._historyValues.get(entityId);

    if (result) {
      return {
        entity: entry?.entity,
        outcome: result.outcome,
        valueLabel: entry?.label,
      };
    }

    // No outcome recorded for this entity yet (e.g. before the first history
    // fetch): use the snapshot when one exists, else the live state.
    return {
      entity: entry?.entity || this.hass?.states?.[entityId],
    };
  }

  private _onDateChanged = (event: Event) => {
    const value = (event.target as HTMLInputElement).value;
    if (!value) return;
    this._selectedDate = value;
    this._scheduleHistoryFetch(0);
  };

  private _shiftSelectedDate(days: number): void {
    if (!this._selectedDate) {
      this._initializeTimeSelection();
    }

    const baseDate = this._getSelectedDateTime();
    baseDate.setDate(baseDate.getDate() + days);
    this._selectedDate = this._toDateInputValue(baseDate);
    this._scheduleHistoryFetch(0);
  }

  private _goToPreviousDay = () => {
    this._shiftSelectedDate(-1);
  };

  private _goToNextDay = () => {
    this._shiftSelectedDate(1);
  };

  private _onTimeSliderChanged = (event: Event) => {
    const minutes = Number((event.target as HTMLInputElement).value);
    this._selectedMinute = Number.isFinite(minutes) ? Math.max(0, Math.min(1439, minutes)) : 0;
    this._scheduleHistoryFetch(120);
  };

  private _jumpToNow = () => {
    const now = new Date();
    this._selectedDate = this._toDateInputValue(now);
    this._selectedMinute = now.getHours() * 60 + now.getMinutes();
    this._scheduleHistoryFetch(0);
  };

  private getProductionValue(entity: HassEntity | undefined): number {
    if (!entity) return 0;

    const value = parseFloat(entity.state);
    return isNaN(value) ? 0 : value;
  }

  private getMaxValue(panelConfig: SolarPanelConfig, unit: string): number {
    if (unit === 'kWh' || unit === 'Wh') {
      const maxDaily = panelConfig.max_daily_production || 5.5;
      // If unit is Wh, convert max_daily_production from kWh to Wh
      return unit === 'Wh' ? maxDaily * 1000 : maxDaily;
    }
    return panelConfig.max_production || 400;
  }

  private snapToGrid(value: number): number {
    if (this.gridSize <= 0) return value;
    return Math.round(value / this.gridSize) * this.gridSize;
  }

  private _clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
  }

  private _clampZoom(value: number): number {
    return this._clamp(value, 1, 5);
  }

  private _getViewportMetrics(): { width: number; height: number } {
    const size = this.getContainerSize();
    const canvasRotation = this.config.canvas_rotation || 0;
    const rotatedSize = this.getRotatedBounds(size.width, size.height, canvasRotation);
    const scale = this._scale || 1;

    return {
      width: Math.max(1, Math.round(rotatedSize.width * scale)),
      height: Math.max(1, Math.round(rotatedSize.height * scale)),
    };
  }

  private _applyPan(panX: number, panY: number): void {
    const zoom = this._clampZoom(this._viewZoom);
    const metrics = this._getViewportMetrics();
    const maxPanX = Math.max(0, (metrics.width * zoom - metrics.width) / 2);
    const maxPanY = Math.max(0, (metrics.height * zoom - metrics.height) / 2);
    const clampedX = this._clamp(panX, -maxPanX, maxPanX);
    const clampedY = this._clamp(panY, -maxPanY, maxPanY);

    if (Math.abs(this._viewPanX - clampedX) > 0.01 || Math.abs(this._viewPanY - clampedY) > 0.01) {
      this._viewPanX = clampedX;
      this._viewPanY = clampedY;
    }
  }

  private _applyZoomAt(targetZoom: number, focusX: number, focusY: number): void {
    const nextZoom = this._clampZoom(targetZoom);
    const currentZoom = this._clampZoom(this._viewZoom);
    const metrics = this._getViewportMetrics();
    const centerX = metrics.width / 2;
    const centerY = metrics.height / 2;

    const worldX = (focusX - centerX - this._viewPanX) / currentZoom;
    const worldY = (focusY - centerY - this._viewPanY) / currentZoom;

    this._viewZoom = nextZoom;

    const nextPanX = focusX - centerX - worldX * nextZoom;
    const nextPanY = focusY - centerY - worldY * nextZoom;
    this._applyPan(nextPanX, nextPanY);
  }

  private _resetViewportTransform = () => {
    this._viewZoom = 1;
    this._viewPanX = 0;
    this._viewPanY = 0;
  };

  private _getPointInViewport(event: MouseEvent | PointerEvent | WheelEvent): { x: number; y: number } {
    const target = this.shadowRoot?.querySelector('.canvas-wrapper') as HTMLElement | null;
    if (!target) {
      return { x: 0, y: 0 };
    }

    const rect = target.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  private _getPointerDistance(): number {
    const points = Array.from(this._activePointers.values());
    if (points.length < 2) {
      return 0;
    }

    const dx = points[1].x - points[0].x;
    const dy = points[1].y - points[0].y;
    return Math.hypot(dx, dy);
  }

  private _getPointerMidpoint(): { x: number; y: number } | null {
    const points = Array.from(this._activePointers.values());
    if (points.length < 2) {
      return null;
    }

    return {
      x: (points[0].x + points[1].x) / 2,
      y: (points[0].y + points[1].y) / 2,
    };
  }

  private _onViewportWheel = (event: WheelEvent) => {
    if (this.isEditorPreview) {
      return;
    }

    event.preventDefault();
    const zoomFactor = Math.exp(-event.deltaY * 0.0015);
    const point = this._getPointInViewport(event);
    this._applyZoomAt(this._viewZoom * zoomFactor, point.x, point.y);
  };

  private _onViewportPointerDown = (event: PointerEvent) => {
    if (this.isEditorPreview) {
      return;
    }
    if (event.pointerType === 'mouse' && event.button !== 0) {
      return;
    }

    const point = this._getPointInViewport(event);
    this._activePointers.set(event.pointerId, point);

    const wrapper = this.shadowRoot?.querySelector('.canvas-wrapper') as HTMLElement | null;
    if (wrapper && wrapper.setPointerCapture) {
      try {
        wrapper.setPointerCapture(event.pointerId);
      } catch {
        // Ignore browsers that fail capture for this pointer.
      }
    }

    if (this._activePointers.size === 1) {
      this._isViewportPanning = true;
      this._panStartPoint = point;
      this._panStartOffset = { x: this._viewPanX, y: this._viewPanY };
    }

    if (this._activePointers.size === 2) {
      this._isViewportPanning = false;
      this._pinchLastDistance = this._getPointerDistance();
      this._pinchLastMidpoint = this._getPointerMidpoint();
      this._suppressPanelClick = true;
    }
  };

  private _onViewportPointerMove = (event: PointerEvent) => {
    if (this.isEditorPreview) {
      return;
    }
    if (!this._activePointers.has(event.pointerId)) {
      return;
    }

    const point = this._getPointInViewport(event);
    this._activePointers.set(event.pointerId, point);

    if (this._activePointers.size >= 2) {
      event.preventDefault();
      const distance = this._getPointerDistance();
      const midpoint = this._getPointerMidpoint();

      if (distance > 0 && this._pinchLastDistance > 0 && midpoint) {
        const zoomFactor = distance / this._pinchLastDistance;
        this._applyZoomAt(this._viewZoom * zoomFactor, midpoint.x, midpoint.y);

        if (this._pinchLastMidpoint) {
          const dx = midpoint.x - this._pinchLastMidpoint.x;
          const dy = midpoint.y - this._pinchLastMidpoint.y;
          this._applyPan(this._viewPanX + dx, this._viewPanY + dy);
        }
      }

      this._pinchLastDistance = distance;
      this._pinchLastMidpoint = midpoint;
      this._suppressPanelClick = true;
      return;
    }

    if (this._isViewportPanning && this._activePointers.size === 1) {
      event.preventDefault();
      const dx = point.x - this._panStartPoint.x;
      const dy = point.y - this._panStartPoint.y;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
        this._suppressPanelClick = true;
      }
      this._applyPan(this._panStartOffset.x + dx, this._panStartOffset.y + dy);
    }
  };

  private _onViewportPointerUp = (event: PointerEvent) => {
    if (this.isEditorPreview) {
      return;
    }

    this._activePointers.delete(event.pointerId);
    if (this._activePointers.size < 2) {
      this._pinchLastDistance = 0;
      this._pinchLastMidpoint = null;
    }

    if (this._activePointers.size === 1) {
      const remainingPoint = Array.from(this._activePointers.values())[0];
      this._isViewportPanning = true;
      this._panStartPoint = remainingPoint;
      this._panStartOffset = { x: this._viewPanX, y: this._viewPanY };
      return;
    }

    this._isViewportPanning = false;
  };



  private onPanelMouseDown(e: MouseEvent, entityId: string) {
    // only allow dragging inside the editor preview
    if (!this.isEditorPreview) {
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    this.draggedPanel = entityId;

    const panel = this.panels.get(entityId);
    if (!panel) return;

    const container = this.shadowRoot?.querySelector('.solar-grid-container') as HTMLElement;
    if (!container) return;


    const containerRect = container.getBoundingClientRect();

    // Calculate offset from mouse position to panel's top-left corner
    const scale = this._scale || 1;
    this.dragOffset = {
      x: e.clientX - (containerRect.left + panel.config.x * scale),
      y: e.clientY - (containerRect.top + panel.config.y * scale),
    };

    document.addEventListener('mousemove', this.onMouseMove);
    document.addEventListener('mouseup', this.onMouseUp);
  }

  private onPanelClick(e: MouseEvent, entityId: string) {
    e.preventDefault();
    e.stopPropagation();

    if (this._suppressPanelClick) {
      this._suppressPanelClick = false;
      return;
    }

    // ignore event if panel is being dragged
    if (this.draggedPanel === entityId) {
      return;
    }

    // In energy view, open the energy entity's info dialog if available
    const panel = this.panels.get(entityId);
    const clickEntityId = (this._showEnergy && panel?.config.entity_energy)
      ? panel.config.entity_energy
      : entityId;

    const event = new CustomEvent('hass-more-info', {
      bubbles: true,
      composed: true,
      detail: { entityId: clickEntityId },
    });
    this.dispatchEvent(event);
  }

  private onMouseMove = (e: MouseEvent) => {
    e.preventDefault();
    if (!this.draggedPanel) return;

    const panel = this.panels.get(this.draggedPanel);
    if (!panel) return;

    const container = this.shadowRoot?.querySelector('.solar-grid-container') as HTMLElement;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const scale = this._scale || 1;
    let x = (e.clientX - rect.left - this.dragOffset.x) / scale;
    let y = (e.clientY - rect.top - this.dragOffset.y) / scale;

    // Clamp to container bounds
    x = Math.max(0, Math.min(x, this.containerWidth - this.panelWidth));
    y = Math.max(0, Math.min(y, this.containerHeight - this.panelHeight));

    // Snap to grid
    x = this.snapToGrid(x);
    y = this.snapToGrid(y);

    const oldX = panel.config.x;
    const oldY = panel.config.y;

    // Update panel position by creating a new config object
    panel.config = { ...panel.config, x, y };

    this.requestUpdate();

  };

  private onMouseUp = () => {
    this.draggedPanel = null;
    document.removeEventListener('mousemove', this.onMouseMove);
    document.removeEventListener('mouseup', this.onMouseUp);

    // Update config with current panel positions
    const updatedPanels = Array.from(this.panels.values()).map((p) => p.config);
    const updatedConfig = {
      ...this.config,
      panels: updatedPanels,
    };

    this.config = updatedConfig;

    // Build positions map
    const positions: Record<string, { x: number; y: number }> = {};
    this.panels.forEach((panel, entityId) => {
      positions[entityId] = {
        x: panel.config.x,
        y: panel.config.y,
      };
    });

    // Dispatch a custom event to notify the editor of position changes
    window.dispatchEvent(
      new CustomEvent('solar-panel-positions-changed', {
        detail: { positions },
      })
    );

    // Dispatch config-changed event for Home Assistant to persist
    const event = new CustomEvent('config-changed', {
      detail: { config: updatedConfig },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  };


  /**
   * Get current panel positions
   * Returns a map of entity_id -> {x, y} coordinates
   */
  public getCurrentPanelPositions(): Record<string, { x: number; y: number }> {
    const positions: Record<string, { x: number; y: number }> = {};
    this.panels.forEach((panel, entityId) => {
      positions[entityId] = {
        x: panel.config.x,
        y: panel.config.y,
      };
    });
    return positions;
  }

  connectedCallback() {
    super.connectedCallback();
    // Inject CSS into document to override dashboard width constraints
    this.injectCSSOverrides();
    // Use ResizeObserver to actively enforce the width override
    this.enforceFullWidth();
    // panels map will be populated in update() when config changes
  }

  firstUpdated() {
    this._resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const availableWidth = entry.contentRect.width;
        const size = this.getContainerSize();
        const canvasRotation = this.config.canvas_rotation || 0;
        const rotatedSize = this.getRotatedBounds(size.width, size.height, canvasRotation);

        let newScale = 1;
        // Only scale down if it exceeds available width
        if (availableWidth > 0 && availableWidth < rotatedSize.width) {
          newScale = availableWidth / rotatedSize.width;
        }

        if (Math.abs(this._scale - newScale) > 0.001) {
          this._scale = newScale;
        }
      }
    });
    const content = this.shadowRoot?.querySelector('.card-content');
    if (content) {
      this._resizeObserver.observe(content);
    }
  }

  private enforceFullWidth() {
    // Use setInterval to actively enforce width on parent elements
    const enforcer = setInterval(() => {
      try {
        let parent = this.parentElement;
        let foundHuiCard = false;
        
        while (parent) {
          if (parent.tagName === 'HUI-CARD') {
            const width = parent.offsetWidth;
            const viewportWidth = window.innerWidth;
            
            // If the card is narrower than viewport, force it wider
            if (width < viewportWidth * 0.9) {
              parent.style.cssText = 'max-width: none !important; width: 100% !important; box-sizing: border-box !important;';
              // width enforcement applied
              foundHuiCard = true;
            }
            break;
          }
          parent = parent.parentElement;
        }
        
        // If we found and fixed constraints, we can stop the interval
        if (foundHuiCard) {
          setTimeout(() => clearInterval(enforcer), 500);
        }
      } catch (e) {
        console.error('[SolarPanelGridCard] Error enforcing width:', e);
      }
    }, 100);
    
    // Stop trying after 10 seconds
    setTimeout(() => clearInterval(enforcer), 10000);
  }

  private injectCSSOverrides() {
    // Check if we've already injected the styles
    if (document.getElementById('solar-panel-grid-card-overrides')) {
      return;
    }

    const style = document.createElement('style');
    style.id = 'solar-panel-grid-card-overrides';
    style.textContent = `
      /* Override the dashboard's media query constraint */
      @media (min-width: 1000px) {
        .content hui-card {
          max-width: none !important;
          width: 100% !important;
        }
      }
      
      /* Target parent containers */
      hui-card[preview] {
        max-width: none !important;
        width: 100% !important;
      }
      
      .element-preview {
        max-width: none !important;
        width: 100% !important;
      }
      
      .content {
        max-width: none !important;
        width: 100% !important;
      }
      
      /* Target the card element directly */
      solar-panel-grid-card {
        max-width: none !important;
        width: 100% !important;
        display: block !important;
      }
      
      /* Override ha-card constraints */
      solar-panel-grid-card ha-card {
        width: 100% !important;
        max-width: none !important;
      }
    `;
    document.head.appendChild(style);
    
    // Also try to directly modify the nearest hui-card element
    try {
      let parent = this.parentElement;
      while (parent) {
        if (parent.tagName === 'HUI-CARD') {
          parent.style.cssText = 'max-width: none !important; width: 100% !important;';
          // modified hui-card parent styles
          break;
        }
        parent = parent.parentElement;
      }
      
      // Also try to modify .content if found
      const contentEl = document.querySelector('.content');
      if (contentEl) {
        // TypeScript doesn’t know this is an HTMLElement
        (contentEl as HTMLElement).style.cssText = 'max-width: none !important; width: 100% !important;';
        // modified .content styles
      }
    } catch (e) {
      console.error('[SolarPanelGridCard] Error modifying parent styles:', e);
    }
    
    // CSS overrides injected
  }

  private getPanelDisplayName(entityId: string, panelConfig: SolarPanelConfig): string {
    // prefer user-specified name, fallback to last 4 chars of the entity id
    return panelConfig.name ? panelConfig.name : entityId.slice(-4);
  }

  private getRotatedBounds(w: number, h: number, angleDeg: number): { width: number; height: number } {
    if (!angleDeg) return { width: w, height: h };
    const rad = Math.abs(angleDeg) * Math.PI / 180;
    return {
      width: Math.ceil(w * Math.cos(rad) + h * Math.sin(rad)),
      height: Math.ceil(w * Math.sin(rad) + h * Math.cos(rad)),
    };
  }

  private _hasEnergyEntities(): boolean {
    return Array.from(this.panels.values()).some((p) => !!p.config.entity_energy);
  }

  private _toggleView = () => {
    this._showEnergy = !this._showEnergy;
    this._saveViewState(this._showEnergy);
  };

  /**
   * Compute the container size based on panel positions.
   * In editor preview mode, use a large workspace so panels can be placed freely.
   * In dashboard mode, fit tightly around the panels (with padding).
   */
  private getContainerSize(): { width: number; height: number } {
    const PADDING = 20; // px padding around content

    // If explicit canvas dimensions are configured, always use them
    if (this.config.canvas_width && this.config.canvas_height) {
      return { width: this.config.canvas_width, height: this.config.canvas_height };
    }

    if (this.isEditorPreview) {
      // In editor, use a large workspace for layout building
      return { width: this.containerWidth, height: this.containerHeight };
    }

    // Calculate bounding box of all panels
    let maxX = 0;
    let maxY = 0;
    this.panels.forEach((panel) => {
      const right = panel.config.x + this.panelWidth;
      const bottom = panel.config.y + this.panelHeight;
      if (right > maxX) maxX = right;
      if (bottom > maxY) maxY = bottom;
    });

    // If no panels, use a minimal size
    if (maxX === 0 && maxY === 0) {
      return { width: 200, height: 200 };
    }

    return {
      width: maxX + PADDING,
      height: maxY + PADDING,
    };
  }

  private _renderTopControls(hasEnergy: boolean) {
    const energyToggleMarkup = hasEnergy
      ? htmlFromTpl(
          cardEnergyToggleTpl,
          this._toggleView,
          `toggle-label ${!this._showEnergy ? 'active' : ''}`,
          `toggle-track ${this._showEnergy ? 'on' : ''}`,
          `toggle-label ${this._showEnergy ? 'active' : ''}`
        )
      : '';

    return htmlFromTpl(
      cardTopControlsTpl,
      this._goToPreviousDay,
      this._goToNextDay,
      this._selectedDate,
      this._onDateChanged,
      String(this._selectedMinute),
      this._onTimeSliderChanged,
      this._minutesToLabel(this._selectedMinute),
      this._jumpToNow,
      energyToggleMarkup
    );
  }

  private _renderHistoryMeta() {
    const statusMarkup = this._historyLoading ? htmlFromTpl(cardHistoryStatusTpl) : '';
    const snapshot = this._historySnapshot;
    const selectionLabel = this._describeSelection();
    const snapshotLabel = snapshot?.label || '—';
    const errorMarkup = this._historyError
      ? htmlFromTpl(cardHistoryErrorTpl, this._historyError)
      : '';

    return htmlFromTpl(
      cardHistoryMetaTpl,
      selectionLabel,
      snapshotLabel,
      statusMarkup,
      errorMarkup
    );
  }

  private _describeSelection(): string {
    return `${this._getSelectedDateTime().toLocaleDateString()} ${this._minutesToLabel(this._selectedMinute)}`;
  }

  /**
   * Outcome badge for one entity. "record" renders a compact check, every
   * other outcome gets a distinct visible label so "no production" and "could
   * not fetch" are never confused. When a panel has an energy entity the
   * badge is prefixed with P:/E: so the two outcomes stay attributable.
   */
  private _renderEntityOutcomeBadge(
    entityId: string,
    outcome: HistoryOutcome | undefined,
    valueLabel?: string,
    prefix = ''
  ) {
    if (!outcome) {
      return '';
    }

    const baseLabel = HISTORY_OUTCOME_LABELS[outcome];
    let label = baseLabel;
    let tooltip = `${entityId}: ${baseLabel.toLowerCase()}.`;

    if (outcome === 'record') {
      label = '✓';
      tooltip = `${entityId}: history record loaded for the selected day/time.`;
    } else if (outcome === 'empty') {
      tooltip = `${entityId}: no history record for the selected day/time.`;
    } else if (valueLabel) {
      label = `${baseLabel} · kept`;
      tooltip = `${entityId}: ${baseLabel.toLowerCase()}; showing the last successful value from ${valueLabel}.`;
    } else {
      tooltip = `${entityId}: ${baseLabel.toLowerCase()}; no previous value to keep.`;
    }

    return htmlFromTpl(
      cardPanelStatusTpl,
      prefix ? `${prefix} ${label}` : label,
      tooltip,
      entityId,
      outcome
    );
  }

  private _renderPanelOutcomes(
    entityId: string,
    energyEntityId: string | undefined,
    powerInfo: { outcome?: HistoryOutcome; valueLabel?: string },
    energyInfo: { outcome?: HistoryOutcome; valueLabel?: string }
  ) {
    const prefixFor = (suffix: string) => (energyEntityId ? suffix : '');

    const powerBadge = this._renderEntityOutcomeBadge(
      entityId,
      powerInfo.outcome,
      powerInfo.valueLabel,
      prefixFor('P:')
    );
    const energyBadge = energyEntityId
      ? this._renderEntityOutcomeBadge(
          energyEntityId,
          energyInfo.outcome,
          energyInfo.valueLabel,
          'E:'
        )
      : '';

    if (!powerBadge && !energyBadge) {
      return '';
    }

    return htmlFromTpl(cardPanelOutcomesTpl, powerBadge, energyBadge);
  }

  private _renderPanel(entityId: string, panel: { config: SolarPanelConfig; entity?: HassEntity; entityEnergy?: HassEntity }, canvasRotation: number) {
    const rotation = panel.config.rotation || 0;
    const totalRotation = rotation + canvasRotation;
    const powerInfo = this._getDisplayEntityInfo(entityId);
    const energyEntityId = panel.config.entity_energy;
    const energyInfo = this._getDisplayEntityInfo(energyEntityId);
    const useEnergy = this._showEnergy && !!energyEntityId;
    const activeInfo = useEnergy ? energyInfo : powerInfo;
    const activeEntity = activeInfo.entity;
    const panelStyle = `left: ${panel.config.x}px; top: ${panel.config.y}px; width: ${this.panelWidth}px; height: ${this.panelHeight}px;${rotation ? ` transform: rotate(${rotation}deg);` : ''}`;
    const panelValueStyle = totalRotation ? `transform: rotate(${-totalRotation}deg)` : '';
    const entitySuffixStyle = totalRotation ? `transform: rotate(${-totalRotation}deg)` : '';
    const backgroundColor = this.getProductionColor(
      this.getProductionValue(activeEntity),
      this.getMaxValue(
        panel.config,
        activeEntity?.attributes.unit_of_measurement || 'W'
      )
    );

    const activeEntityId = useEnergy ? energyEntityId! : entityId;
    let panelValueMarkup;
    if (activeEntity) {
      panelValueMarkup = htmlFromTpl(
        cardPanelValueTpl,
        this.getProductionValue(activeEntity).toFixed(1),
        activeEntity.attributes.unit_of_measurement || ''
      );
    } else if (activeInfo.outcome === 'empty') {
      panelValueMarkup = htmlFromTpl(
        cardPanelMissingTpl,
        'No record',
        `${activeEntityId}: no history record for the selected day/time.`
      );
    } else if (activeInfo.outcome === 'invalid') {
      panelValueMarkup = htmlFromTpl(cardPanelErrorTpl, 'Bad data');
    } else {
      panelValueMarkup = htmlFromTpl(cardPanelErrorTpl, 'N/A');
    }

    const outcomesMarkup = this._renderPanelOutcomes(
      entityId,
      energyEntityId,
      powerInfo,
      energyInfo
    );

    return htmlFromTpl(
      cardPanelTpl,
      panelStyle,
      (e: MouseEvent) => this.onPanelClick(e, entityId),
      (e: MouseEvent) => this.onPanelMouseDown(e, entityId),
      backgroundColor,
      this.panelImage,
      panelValueStyle,
      panelValueMarkup,
      entitySuffixStyle,
      this.getPanelDisplayName(entityId, panel.config),
      entityId,
      activeInfo.outcome || '',
      powerInfo.outcome || '',
      energyInfo.outcome || '',
      outcomesMarkup
    );
  }

  private _renderCanvas(
    size: { width: number; height: number },
    canvasRotation: number,
    bgImage: string,
    bgOpacity: number,
    wrapperWidth: number,
    wrapperHeight: number,
    liveInteractionEnabled: boolean,
    panX: number,
    panY: number,
    combinedScale: number
  ) {
    const wrapperClass = `canvas-wrapper ${liveInteractionEnabled ? 'interactive' : ''}`;
    const rotationStyle = canvasRotation ? ` rotate(${canvasRotation}deg)` : '';
    const backgroundMarkup = bgImage ? htmlFromTpl(cardBackgroundImageTpl, bgImage, bgOpacity) : '';
    const panelMarkup = Array.from(this.panels.entries()).map(([entityId, panel]) => this._renderPanel(entityId, panel, canvasRotation));

    return htmlFromTpl(
      cardCanvasTpl,
      wrapperClass,
      wrapperWidth,
      wrapperHeight,
      this._onViewportWheel,
      this._onViewportPointerDown,
      this._onViewportPointerMove,
      this._onViewportPointerUp,
      this._onViewportPointerUp,
      this._resetViewportTransform,
      size.width,
      size.height,
      size.width / 2,
      size.height / 2,
      panX,
      panY,
      combinedScale,
      rotationStyle,
      backgroundMarkup,
      panelMarkup
    );
  }

  render() {
    const size = this.getContainerSize();
    const canvasRotation = this.config.canvas_rotation || 0;
    const rotatedSize = this.getRotatedBounds(size.width, size.height, canvasRotation);
    const bgImage = this.config.background_image || '';
    const bgOpacity = this.config.background_opacity ?? 0.4;
    const hasEnergy = this._hasEnergyEntities();
    const baseScale = this._scale || 1;
    const wrapperWidth = Math.round(rotatedSize.width * baseScale);
    const wrapperHeight = Math.round(rotatedSize.height * baseScale);
    const liveInteractionEnabled = !this.isEditorPreview;
    const viewZoom = liveInteractionEnabled ? this._viewZoom : 1;
    const panX = liveInteractionEnabled ? this._viewPanX : 0;
    const panY = liveInteractionEnabled ? this._viewPanY : 0;
    const combinedScale = baseScale * viewZoom;

    return htmlFromTpl(
      cardRenderTpl,
      this._renderTopControls(hasEnergy),
      this._renderHistoryMeta(),
      this._renderCanvas(
        size,
        canvasRotation,
        bgImage,
        bgOpacity,
        wrapperWidth,
        wrapperHeight,
        liveInteractionEnabled,
        panX,
        panY,
        combinedScale
      )
    );
  }

  private static readonly CARD_STYLES = css`${unsafeCSS(cardStyles)}`;

  static styles = SolarPanelGridCard.CARD_STYLES;
}

// Register the custom element
customElements.define('solar-panel-grid-card', SolarPanelGridCard);

declare global {
  interface HTMLElementTagNameMap {
    'solar-panel-grid-card': SolarPanelGridCard;
  }
}
