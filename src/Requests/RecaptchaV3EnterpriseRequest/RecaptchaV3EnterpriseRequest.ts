import { TaskType } from '../../TaskType';
import { RecaptchaV3EnterpriseRequestBase, RecaptchaV3EnterpriseRequestBaseIn } from './RecaptchaV3EnterpriseRequestBase';

export type RecaptchaV3EnterpriseRequestIn = Pick<
  RecaptchaV3EnterpriseRequestBaseIn,
  Exclude<keyof RecaptchaV3EnterpriseRequestBaseIn, 'type'>
>;

/**
 * Recaptcha V3 Enterprise recognition request.
 * {@link https://zenno.link/doc-recaptcha3e-proxy-en}
 */

export class RecaptchaV3EnterpriseRequest extends RecaptchaV3EnterpriseRequestBase {
  constructor({ ...restArgsObj }: RecaptchaV3EnterpriseRequestIn) {
    super({ type: TaskType.RecaptchaV3EnterpriseTask, ...restArgsObj });
  }
}
