import {OlostepTransport} from '../http/transport.js';
import {AnswerRequest} from '../types.js';
import {OlostepResource} from './base.js';
import {AnswerResult} from '../client_state/AnswerResult.js';
import {normalizeToCamel} from '../casing.js';

const normalizeAnswerInput = (input: string | AnswerRequest): AnswerRequest =>
  typeof input === 'string' ? {task: input} : input;

const buildAnswerPayload = (input: AnswerRequest) => ({
  task: input.task,
  json_format: input.jsonFormat
});

export class AnswerNamespace extends OlostepResource {
  constructor(transport: OlostepTransport) {
    super(transport);
  }

  async create(input: string | AnswerRequest) {
    const normalized = normalizeToCamel(normalizeAnswerInput(input));
    const payload = buildAnswerPayload(normalized);
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'POST',
      path: '/answers',
      body: payload
    });
    return new AnswerResult(data);
  }

  async get(answerId: string) {
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'GET',
      path: `/answers/${answerId}`
    });
    return new AnswerResult(data);
  }
}
