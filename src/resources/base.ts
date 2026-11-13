import {OlostepTransport} from '../http/transport.js';

export abstract class OlostepResource {
  constructor(protected readonly transport: OlostepTransport) {}
}

