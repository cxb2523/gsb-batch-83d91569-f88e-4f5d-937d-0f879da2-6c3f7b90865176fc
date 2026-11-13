export interface SearchLink {
  url: string;
  title: string;
  description: string;
  markdown_content?: string | null;
  html_content?: string | null;
}

export class SearchResult {
  public readonly id: string;
  public readonly object: string;
  public readonly created: number;
  public readonly metadata: Record<string, unknown>;
  public readonly query: string;
  public readonly credits_consumed: number;

  public readonly links: SearchLink[];
  public readonly json_content?: string | null;
  public readonly json_hosted_url?: string | null;
  public readonly size_exceeded: boolean;

  [key: string]: unknown;

  constructor(data: Record<string, unknown>) {
    this.id = data.id as string;
    this.object = (data.object as string) ?? 'search';
    this.created = data.created as number;
    this.metadata = (data.metadata as Record<string, unknown>) ?? {};
    this.query = data.query as string;
    this.credits_consumed = (data.credits_consumed as number) ?? 0;

    const result = (data.result as Record<string, unknown>) ?? {};
    this.links = (result.links as SearchLink[]) ?? [];
    this.json_content = result.json_content as string | null | undefined;
    this.json_hosted_url = result.json_hosted_url as string | null | undefined;
    this.size_exceeded = (result.size_exceeded as boolean) ?? false;
  }

  public toString(): string {
    const queryStr = this.query.length > 50 ? this.query.slice(0, 50) + '...' : this.query;
    return `SearchResult(id=${this.id}, query=${queryStr}, links=${this.links.length})`;
  }
}
