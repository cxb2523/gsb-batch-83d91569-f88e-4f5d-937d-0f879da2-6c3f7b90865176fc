export interface ScrapeStorageResult {
  /** Effective retention duration. One of: `"7d"`, `"10d"`, `"30d"`, `"60d"`, `"90d"`, `"180d"`, `"365d"`, `"never"`. */
  expires_in: string;
}

// ScrapeResult mirrors the snake_case fields returned by the Olostep API.
export class ScrapeResult {
  public readonly id?: string;
  public readonly object?: string;
  public readonly created?: number;
  public readonly metadata?: Record<string, unknown> | null;
  public readonly retrieve_id?: string;
  public readonly url_to_scrape?: string;
  public readonly result?: Record<string, unknown>;
  /** Storage retention info returned by the API. */
  public readonly storage?: ScrapeStorageResult | null;

  public readonly html_content?: string;
  public readonly markdown_content?: string;
  public readonly text_content?: string;
  public readonly json_content?: unknown;

  public readonly html_hosted_url?: string;
  public readonly markdown_hosted_url?: string;
  public readonly json_hosted_url?: string;
  public readonly text_hosted_url?: string;
  public readonly screenshot_hosted_url?: string;

  public readonly links_on_page?: unknown;
  public readonly page_metadata?: unknown;
  public readonly llm_extract?: unknown;
  public readonly network_calls?: unknown;
  public readonly size_exceeded?: boolean;
  public readonly image_queued?: boolean;

  [key: string]: unknown;

  constructor(data: Record<string, unknown>) {
    Object.assign(this, data);
    if (data.result && typeof data.result === 'object') {
      Object.assign(this, data.result as Record<string, unknown>);
    }
  }

  public toString(): string {
    const keys = Object.keys(this).filter(
      (key) => key.endsWith('_content') || key.endsWith('_hosted_url')
    );
    return `ScrapeResult(id=${this.id}, available=[${keys.join(', ')}])`;
  }
}
