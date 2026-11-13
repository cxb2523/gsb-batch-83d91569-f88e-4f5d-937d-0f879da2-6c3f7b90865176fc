import { TaskType } from '../../TaskType';
import { HuntRequestBase, HuntRequestBaseIn } from './HuntRequestBase';
import { ProxyInfo, ProxyInfoIn } from '../ProxyInfo';

export type HuntRequestIn = Pick<HuntRequestBaseIn, Exclude<keyof HuntRequestBaseIn, 'type' | '_class'>> & {
  proxy: ProxyInfoIn;
};

export class HuntRequest extends HuntRequestBase {
  public declare class: 'HUNT';

  constructor({ proxy, ...argsObj }: HuntRequestIn) {
    super({ type: TaskType.CustomTask, _class: 'HUNT', ...argsObj });
    Object.assign(this, new ProxyInfo(proxy));
  }
}
