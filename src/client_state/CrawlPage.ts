export class CrawlPage {
  public readonly id?: string;
  public readonly retrieve_id?: string;
  public readonly url?: string;
  public readonly is_external?: boolean;
  [key: string]: unknown;

  constructor(data: Record<string, unknown>) {
    Object.assign(this, data);
    this.id = data.id as string | undefined;
    this.retrieve_id = data.retrieve_id as string | undefined;
    this.url = data.url as string | undefined;
    this.is_external = data.is_external as boolean | undefined;
  }
}
