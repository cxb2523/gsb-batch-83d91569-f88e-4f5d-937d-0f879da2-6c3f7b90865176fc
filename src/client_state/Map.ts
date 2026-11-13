import {OlostepTransport} from '../http/transport.js';

interface MapHandleData extends Record<string, unknown> {
  id: string;
  urls?: string[];
}

export class Map {
  public readonly id: string;
  private readonly transport: OlostepTransport;
  private readonly urlsList: string[];
  [key: string]: unknown;

  constructor(transport: OlostepTransport, data: MapHandleData) {
    this.transport = transport;
    this.id = data.id;
    this.urlsList = data.urls ?? [];
    
    // Assign all other fields except 'urls' to avoid conflict with urls() method
    const {urls, ...rest} = data;
    Object.assign(this, rest);
  }

  async info(): Promise<unknown> {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/maps/${this.id}`
    });
    return data;
  }

  async *urls(): AsyncGenerator<string> {
    // Map URLs are returned immediately in the creation response
    for (const url of this.urlsList) {
      yield url;
    }
  }
}

