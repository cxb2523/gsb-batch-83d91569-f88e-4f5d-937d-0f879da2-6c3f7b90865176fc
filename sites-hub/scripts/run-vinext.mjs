import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { access, copyFile, unlink } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const cli = fileURLToPath(new URL("../node_modules/vinext/dist/cli.js", import.meta.url));
const hosting = fileURLToPath(new URL("../.openai/hosting.json", import.meta.url));
const hostingExample = fileURLToPath(
  new URL("../.openai/hosting.example.json", import.meta.url),
);

let createdTemporaryHosting = false;
let result;

try {
  try {
    await access(hosting);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    await copyFile(hostingExample, hosting, constants.COPYFILE_EXCL);
    createdTemporaryHosting = true;
  }

  const child = spawn(process.execPath, [cli, process.argv[2] || "dev"], {
    stdio: "inherit",
    env: { ...process.env, WRANGLER_LOG_PATH: ".wrangler/wrangler.log" },
  });

  result = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
} finally {
  if (createdTemporaryHosting) {
    await unlink(hosting);
  }
}

if (result.signal) {
  process.kill(process.pid, result.signal);
} else {
  process.exitCode = result.code ?? 1;
}
