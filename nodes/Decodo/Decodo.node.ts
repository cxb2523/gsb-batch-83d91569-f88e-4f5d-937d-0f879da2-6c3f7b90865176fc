import {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
  NodeConnectionType,
} from 'n8n-workflow';
import { ScraperApiService } from './services/scraper-api-service';
import { detectAuthType } from './services/detect-auth-type';
import { PropertyHandler } from './services/parameter-transformer';
import { TargetProperty } from './properties/target.property';
import { validateScrapingParameters } from './services/parameter-validation';
import {
  asStatusCode,
  attachRetryList,
  buildFailedOutcome,
  buildSkippedOutcome,
  buildSuccessOutcome,
  extractRetryList,
  isInRetryList,
  readTarget,
} from './services/item-outcome';
import { ItemErrorSource, ScraperApiParams } from './types';

// n8n injects the "Custom API Call" option into `operation` at runtime, so it is not in TargetProperty.
const TARGET_NAMES = {
  ...Object.fromEntries(TargetProperty.property.options.map(({ value, name }) => [value, name])),
  __CUSTOM_API_CALL__: 'Custom API Call',
};

export class Decodo implements INodeType {
  static NAME = 'Decodo';

  static CREDS = 'decodoApi';

  description: INodeTypeDescription = {
    displayName: Decodo.NAME,
    name: 'decodo',
    group: ['transform'],
    version: 1,
    description: "Decodo's Web Scraping API",
    icon: 'file:decodo.svg',
    subtitle: `={{ (${JSON.stringify(TARGET_NAMES)})[$parameter["operation"]] }}`,
    defaults: {
      name: Decodo.NAME,
    },
    inputs: [NodeConnectionType.Main],
    outputs: [NodeConnectionType.Main],
    usableAsTool: true,
    credentials: [
      {
        name: Decodo.CREDS,
        required: true,
      },
    ],
    properties: PropertyHandler.properties,
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const returnData: INodeExecutionData[] = [];

    const { token } = await this.getCredentials(Decodo.CREDS);
    const resolvedAuthType = detectAuthType(String(token ?? '').trim());

    // When the input carries the retry list of a previous run, only those indexes
    // are fetched; every other item is reported as skipped without calling the API.
    const retryList = extractRetryList(items);
    const retryIndexes = retryList === null ? null : new Set(retryList);

    const readNodeParameters = (index: number) =>
      PropertyHandler.getParametersWithFallback({
        getNodeParameters: this.getNodeParameter,
        index,
      }) as unknown as Record<string, unknown>;

    for (let i = 0; i < items.length; i++) {
      // `index` and `pairedItem` both identify the current input item, so each
      // record maps to exactly one input and the order is never changed.
      if (!isInRetryList(i, retryIndexes)) {
        let target = readTarget(items[i]);

        try {
          target = readTarget(items[i], readNodeParameters(i)) ?? target;
        } catch {
          // A skipped item must not fail the run; its target is only informative.
        }

        returnData.push(buildSkippedOutcome({ index: i, target }));
        continue;
      }

      let target = readTarget(items[i]);
      let errorSource = ItemErrorSource.VALIDATION;

      try {
        const nodeParameters = readNodeParameters(i);
        target = readTarget(items[i], nodeParameters) ?? target;

        // Rejected locally: no request is sent, the item still yields an outcome.
        validateScrapingParameters(nodeParameters as ScraperApiParams);
        const scrapingParameters = PropertyHandler.transformToScrapingParameters(
          nodeParameters as ScraperApiParams,
        );

        errorSource = ItemErrorSource.API;
        const responseBody = await ScraperApiService.scrape({
          n8n: this,
          creds: Decodo.CREDS,
          authType: resolvedAuthType,
          params: scrapingParameters,
        });

        returnData.push(buildSuccessOutcome({ index: i, target, response: responseBody }));
      } catch (error) {
        // Every input item leaves exactly one outcome, so a single failure no
        // longer aborts the remaining items of the batch.
        returnData.push(
          buildFailedOutcome({
            index: i,
            target,
            error,
            source: errorSource,
            statusCode: errorSource === ItemErrorSource.API ? asStatusCode(error) : null,
          }),
        );
      }
    }

    attachRetryList(returnData);

    return [returnData];
  }
}
