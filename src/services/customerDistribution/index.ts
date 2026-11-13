export * from './types.ts';
export { validateRecord } from './validator.ts';
export { createHttpDataSource, parseCatalog } from './dataSource.ts';
export { collectRegion, RegionCollectionError } from './collector.ts';
export { createCustomerDistributionController } from './controller.ts';
export type { CustomerDistributionController } from './controller.ts';
export {
  buildAuditView,
  buildDistributionView,
  formatTimestamp
} from './viewModel.ts';
export type {
  CollectionAuditView,
  DistributionView,
  StatCardView
} from './viewModel.ts';
