// Smoke test for a packaged build: starts it as a brand-new user (an empty, throwaway profile), loads the
// sample library, opens every screen, then quits and checks that nothing failed along the way.
//
//   node scripts/smoke-packaged.mjs                   the build for this platform in dist/
//   node scripts/smoke-packaged.mjs <path to the app> any other build
//
// It drives the app over Chromium's DevTools protocol (--remote-debugging-port), so it needs no test
// dependencies and works with the Electron fuses that turn off Node's inspector. On Linux without a
// display, run it under xvfb-run. Covers need IGDB's image server; offline they show empty frames, which
// is not a failure.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const DEFAULT_APPS = {
  win32: "dist/win-unpacked/Game Release Tracker.exe",
  linux: "dist/linux-unpacked/game-release-tracker",
  darwin: "dist/mac/Game Release Tracker.app/Contents/MacOS/Game Release Tracker"
};
const SCREENS = ["Upcoming", "Calendar", "Completed Library", "Randomizer", "Settings", "Year in Review"];
const PORT = Number(process.env.SMOKE_DEBUG_PORT || 9333);
// A request the page never answers (its window died, or a native error dialog is blocking the app) must
// fail the test, not hang it.
const REQUEST_TIMEOUT_MS = 10_000;
const OVERALL_TIMEOUT_MS = 180_000;

const appPath = process.argv[2] ?? DEFAULT_APPS[process.platform];
if (!appPath || !existsSync(appPath)) {
  console.error(`No packaged app at ${appPath}. Build one first (npm run dist), or pass its path.`);
  process.exit(2);
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const failures = [];
const profile = mkdtempSync(join(tmpdir(), "grt-smoke-"));
const args = [`--user-data-dir=${profile}`, `--remote-debugging-port=${PORT}`];
if (process.platform === "linux") args.push("--no-sandbox");
const app = spawn(appPath, args, { stdio: "ignore" });
const exited = new Promise(resolve => app.once("exit", code => resolve(code)));
const watchdog = setTimeout(() => {
  console.error(`\nSmoke test failed: still running after ${OVERALL_TIMEOUT_MS / 1000} seconds`);
  app.kill("SIGKILL");
  rmSync(profile, { recursive: true, force: true });
  process.exit(1);
}, OVERALL_TIMEOUT_MS);

async function waitFor(check, what, timeoutMs = 20_000) {
  const until = Date.now() + timeoutMs;
  for (;;) {
    const value = await Promise.race([check(), sleep(REQUEST_TIMEOUT_MS)]).catch(() => undefined);
    if (value) return value;
    if (Date.now() > until) throw new Error(`Timed out waiting for ${what}`);
    await sleep(250);
  }
}

// One DevTools session on the app's page.
async function connect() {
  const target = await waitFor(async () => {
    const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    return targets.find(item => item.type === "page" && !item.url.startsWith("devtools:"));
  }, "the app window");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let nextId = 1;
  const pending = new Map();
  socket.onclose = () => {
    for (const settle of pending.values()) settle({ error: { message: "The app window closed" } });
    pending.clear();
  };
  socket.onmessage = message => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) {
      pending.get(data.id)(data);
      pending.delete(data.id);
    } else if (data.method === "Runtime.exceptionThrown") {
      failures.push(`Uncaught error in the page: ${data.params.exceptionDetails.exception?.description ?? data.params.exceptionDetails.text}`);
    } else if (data.method === "Runtime.consoleAPICalled" && data.params.type === "error") {
      failures.push(`Console error: ${data.params.args.map(arg => arg.value ?? arg.description).join(" ")}`);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`The app did not answer ${method} within ${REQUEST_TIMEOUT_MS / 1000} seconds`));
    }, REQUEST_TIMEOUT_MS);
    pending.set(id, data => {
      clearTimeout(timer);
      if (data.error) reject(new Error(data.error.message));
      else resolve(data);
    });
    if (socket.readyState !== WebSocket.OPEN) pending.get(id)({ error: { message: "The app window closed" } });
    else socket.send(JSON.stringify({ id, method, params }));
  });
  await send("Runtime.enable");
  const evaluate = async expression => {
    const { result } = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? "evaluate failed");
    return result.result.value;
  };
  return { evaluate, close: () => socket.close() };
}

// Page-side helpers: find a button by its visible text, and report anything that says it went wrong.
const clickButton = text => `(() => {
  const button = [...document.querySelectorAll("button")].find(item => item.textContent.trim() === ${JSON.stringify(text)} && !item.disabled);
  if (!button) return false;
  button.click();
  return true;
})()`;
const pageProblem = `(() => {
  const problem = document.querySelector(".error-boundary, .operation-error, .state.error");
  return problem ? problem.textContent.trim() : "";
})()`;

let page;
try {
  page = await connect();
  await waitFor(() => page.evaluate(clickButton("Try it with sample data")), "the welcome screen");
  await waitFor(() => page.evaluate(`document.body.textContent.includes("Remove sample data")`), "the sample library to load");
  console.log("ok   sample library loaded");

  for (const screen of SCREENS) {
    await waitFor(() => page.evaluate(clickButton(screen)), `the ${screen} button`);
    await sleep(1500);
    const problem = await page.evaluate(pageProblem);
    if (problem) failures.push(`${screen}: ${problem}`);
    console.log(`${problem ? "FAIL" : "ok  "} ${screen}`);
  }
} catch (error) {
  failures.push(error instanceof Error ? error.message : String(error));
} finally {
  page?.close();
  app.kill();
}

const exitCode = await Promise.race([exited, sleep(10_000).then(() => "still running")]);
if (exitCode === "still running") failures.push("The app did not close within 10 seconds");

// The app's own diagnostics log: an entry named *.failed, *error* or *crash* is a failure. Its log
// holds events, never keys, so it is safe to print.
const logDir = join(profile, "logs");
const logFiles = existsSync(logDir) ? readdirSync(logDir).filter(name => name.endsWith(".log")) : [];
for (const name of logFiles) {
  for (const line of readFileSync(join(logDir, name), "utf8").split("\n")) {
    const event = /"event":"([^"]+)"/.exec(line)?.[1];
    if (event && /fail|error|crash|uncaught|unhandled/i.test(event)) failures.push(`Logged ${event} in ${name}`);
  }
}
rmSync(profile, { recursive: true, force: true });
clearTimeout(watchdog);
if (exitCode === "still running") app.kill("SIGKILL");

if (failures.length) {
  console.error(`\nSmoke test failed:\n${failures.map(item => `- ${item}`).join("\n")}`);
  process.exit(1);
}
console.log("\nSmoke test passed: new profile, sample library, every screen, clean exit, no logged errors.");
