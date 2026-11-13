import {jest} from '@jest/globals';

// Jest setup. In CI, retry each test a couple of times so transient
// network or API blips do not fail the build. Local runs are not
// retried, so real failures show up immediately while developing.
if (process.env.CI) {
  jest.retryTimes(2, {logErrorsBeforeRetry: true});
}
