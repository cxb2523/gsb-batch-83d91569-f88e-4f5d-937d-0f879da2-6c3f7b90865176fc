import { TaskType } from '../../TaskType';
import { TSPDRequestBase, TSPDRequestBaseIn } from './TSPDRequestBase';
import { ProxyInfo, ProxyInfoIn } from '../ProxyInfo';

export type TSPDRequestIn = Pick<TSPDRequestBaseIn, Exclude<keyof TSPDRequestBaseIn, 'type' | '_class'>> & { proxy: ProxyInfoIn };

/**
 * TSPD recognition request.
 */
export class TSPDRequest extends TSPDRequestBase {
  public declare class: 'tspd';

  constructor({ proxy, ...argsObj }: TSPDRequestIn) {
    super({ type: TaskType.CustomTask, _class: 'tspd', ...argsObj });
    Object.assign(this, new ProxyInfo(proxy));
  }
}
