// Test fixtures are dated around September 2026, and the app filters by "this year" and "today". The suite runs
// as if the day were 2026-09-25, with the clock still moving, so a result doesn't depend on the day CI runs.
const SUITE_NOW = Date.parse("2026-09-25T12:00:00Z");
const RealDate = Date;
const offset = SUITE_NOW - RealDate.now();

class SuiteDate extends RealDate {
  constructor(...args: unknown[]) {
    if (args.length === 0) super(RealDate.now() + offset);
    else super(...(args as [string | number | Date]));
  }

  static now() {
    return RealDate.now() + offset;
  }
}

globalThis.Date = SuiteDate as DateConstructor;
