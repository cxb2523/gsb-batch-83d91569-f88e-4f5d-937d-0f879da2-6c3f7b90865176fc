# Third-party notices

Project-authored code and documentation use the MIT license in `LICENSE`.

`src/echarts.min.js` is the unmodified ECharts 6.0.0 distribution from the official npm package. Apache ECharts is licensed under Apache-2.0. Its original `LICENSE`, `NOTICE` and bundled software license declarations are preserved under `third_party/echarts/`. They apply to this vendored file independently of this project's MIT license.

Source: https://github.com/apache/echarts/tree/6.0.0

Wrangler is a development/deployment dependency, not part of the browser bundle. Its packages and their individual license notices are installed by `npm ci`; exact versions are recorded in `package-lock.json`.

The MIT license covers project code and generated synthetic examples. It does not grant rights to FtShare's hosted data service, API credentials, the FtShare name/logo, or third-party market datasets imported by an operator. This repository does not distribute a production market-data snapshot.
