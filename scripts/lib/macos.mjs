import { resolve } from 'node:path';
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&apos;');
function value(item) {
  if (typeof item === 'boolean') return item ? '<true/>' : '<false/>';
  if (typeof item === 'number') return '<integer>' + item + '</integer>';
  if (Array.isArray(item)) return '<array>' + item.map(value).join('') + '</array>';
  if (item && typeof item === 'object') return '<dict>' + Object.entries(item).map(([k, v]) => '<key>' + escape(k) + '</key>' + value(v)).join('') + '</dict>';
  return '<string>' + escape(item) + '</string>';
}
export const plist = object => '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">' + value(object) + '</plist>\n';
export function macJobs({ root, node, port = 8080, demo = false, lan = false }) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be 1–65535');
  const log = resolve(root, '.local/logs');
  const common = { WorkingDirectory: root, ProcessType: 'Background', Umask: 63, EnvironmentVariables: { HOST: lan ? '0.0.0.0' : '127.0.0.1', PORT: String(port), TZ: 'Asia/Shanghai', FTSHARE_BUILD_DIR: resolve(root, '.local/current') } };
  const service = { ...common, Label: 'com.ftshare.etf-dashboard', ProgramArguments: [node, '--env-file=.env', 'scripts/serve.mjs'], KeepAlive: true, RunAtLoad: true, ThrottleInterval: 10,
    StandardOutPath: resolve(log, 'server.log'), StandardErrorPath: resolve(log, 'server-error.log') };
  const refresh = { ...common, Label: 'com.ftshare.etf-dashboard.refresh', ProgramArguments: [node, '--env-file=.env', 'scripts/refresh.mjs'], StartInterval: 21600,
    StandardOutPath: resolve(log, 'refresh.log'), StandardErrorPath: resolve(log, 'refresh-error.log') };
  return demo ? [service] : [service, refresh];
}
