import { TaskType } from '../../TaskType';
import { CastleRequestBase, CastleRequestBaseIn } from './CastleRequestBase';
import { ProxyInfo, ProxyInfoIn } from '../ProxyInfo';

export type CastleRequestIn = Pick<CastleRequestBaseIn, Exclude<keyof CastleRequestBaseIn, 'type' | '_class'>> & { proxy?: ProxyInfoIn };

/**
 * Castle recognition request.
 */
export class CastleRequest extends CastleRequestBase {
  public declare class: 'Castle';

  constructor({ proxy, ...argsObj }: CastleRequestIn) {
    super({ type: TaskType.CustomTask, _class: 'Castle', ...argsObj });

    if (proxy) {
      Object.assign(this, new ProxyInfo(proxy));
    }
  }
}
