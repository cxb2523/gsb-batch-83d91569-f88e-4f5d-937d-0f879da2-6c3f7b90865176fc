// electron-builder afterPack hook: removes Chromium files the app never uses before the package is zipped.
const { rmSync } = require("node:fs");
const { join } = require("node:path");

// The DirectX shader compiler is only for WebGPU. The app draws with canvas 2D, and swiftshader and
// d3dcompiler_47.dll stay for the GPU process.
const unusedWindowsFiles = ["dxcompiler.dll", "dxil.dll"];

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "win32") return;
  for (const file of unusedWindowsFiles) rmSync(join(context.appOutDir, file), { force: true });
};
