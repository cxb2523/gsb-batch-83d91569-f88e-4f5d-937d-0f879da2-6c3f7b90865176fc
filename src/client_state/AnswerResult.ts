export class AnswerResult {
  public readonly id: string;
  public readonly object: string;
  public readonly created: number;
  public readonly metadata: Record<string, unknown>;
  public readonly task: string;

  public readonly json_content?: string | null;
  public readonly json_hosted_url?: string | null;
  public readonly sources: string[];

  [key: string]: unknown;

  constructor(data: Record<string, unknown>) {
    this.id = data.id as string;
    this.object = (data.object as string) ?? 'answer';
    this.created = data.created as number;
    this.metadata = (data.metadata as Record<string, unknown>) ?? {};
    this.task = data.task as string;

    const result = (data.result as Record<string, unknown>) ?? {};
    this.json_content = result.json_content as string | null | undefined;
    this.json_hosted_url = result.json_hosted_url as string | null | undefined;
    this.sources = (result.sources as string[]) ?? [];
  }

  get answer(): string | null {
    if (typeof this.json_content === 'string') return this.json_content;
    return this.json_content != null ? String(this.json_content) : null;
  }

  public toString(): string {
    const taskStr = this.task.length > 50 ? this.task.slice(0, 50) + '...' : this.task;
    return `AnswerResult(id=${this.id}, task=${taskStr}, sources=${this.sources.length})`;
  }
}
