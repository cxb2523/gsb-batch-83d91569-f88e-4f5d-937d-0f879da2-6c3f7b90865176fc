#!/usr/bin/env node
/**
 * Lobster Browser Tool - Zero-config Browser Control
 * A simple yet powerful CLI browser automation tool.
 * 
 * Usage:
 *   lobster-browser-tool start              - Start browser
 *   lobster-browser-tool stop               - Close browser
 *   lobster-browser-tool navigate <url>     - Navigate to URL
 *   lobster-browser-tool screenshot         - Take screenshot
 *   lobster-browser-tool analyze "<prompt>" - AI vision analysis
 *   lobster-browser-tool snapshot           - Get page snapshot
 *   lobster-browser-tool status             - View status
 *   lobster-browser-tool wait <selector>    - Wait for element visible
 *   lobster-browser-tool click <selector>   - Click element
 *   lobster-browser-tool type <selector> <text> - Type text
 */

const { chromium } = require('playwright');
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const { GoogleGenerativeAI } = require('@google/generative-ai');
const { collectSnapshot } = require('./snapshot-extract');

// Configuration
const HOME_DIR = path.join(os.homedir(), '.lobster-browser');
const CONFIG = {
  // Only used when CHROMIUM_PATH is set to an executable file; otherwise Playwright's bundled Chromium is used.
  browserPath: process.env.CHROMIUM_PATH || null,
  headless: process.env.HEADLESS !== 'false',  // Default to headless mode
  dataDir: process.env.LOBSTER_DATA_DIR || path.join(HOME_DIR, 'profile'),
  port: parseInt(process.env.LOBSTER_PORT, 10) || 18791,
  stealth: true,
};

// Gemini API Key / model
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-flash-latest';

const NOT_STARTED = 'Browser not started. Run: lobster-browser-tool start';

// Stealth patch script
const STEALTH_SCRIPT = `
// Playwright Stealth Patch - Manual Implementation
(() => {
  // Hide webdriver
  Object.defineProperty(navigator, 'webdriver', { get: () => false });
  
  // Fake plugins
  Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  
  // Fake language
  Object.defineProperty(navigator, 'language', { get: () => 'en-US' });
  
  // Fake platform
  Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
  
  // Fake hardware concurrency
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  
  // Fake device memory
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  
  // Remove automation markers
  window.cdc_ = undefined;
  
  // Modify Chrome properties
  Object.defineProperty(navigator, 'chrome', { get: () => ({ runtime: {} }) });
  
  console.log('Stealth patch applied');
})();
`;

// State file
const STATE_FILE = path.join(HOME_DIR, 'state.json');

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch (e) {
    return false;
  }
}

// Resolves with the CDP /json/version payload if a browser answers on the port, else null.
function probePort(port) {
  return new Promise((resolve) => {
    const req = http.get({ hostname: '127.0.0.1', port, path: '/json/version', timeout: 1500 }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class BrowserControl {
  constructor() {
    this.browser = null;   // CDP connection (non-start commands)
    this.context = null;   // persistent context (start command only)
    this.page = null;
    this.connected = false;
  }

  readState() {
    try {
      return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    } catch (e) {
      return {};
    }
  }

  saveState(status = 'idle', extra = {}) {
    try {
      fs.mkdirSync(HOME_DIR, { recursive: true });
      const state = {
        browserPath: CONFIG.browserPath || 'playwright-bundled',
        dataDir: CONFIG.dataDir,
        port: CONFIG.port,
        status,
        lastActive: new Date().toISOString(),
        ...extra,
      };
      fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
    } catch (e) {
      console.error('Failed to save state:', e.message);
    }
  }

  // Executable to pass to Playwright, or undefined to use the bundled Chromium
  resolveExecutable() {
    if (!CONFIG.browserPath) return undefined;
    if (isExecutable(CONFIG.browserPath)) return CONFIG.browserPath;
    console.error(`CHROMIUM_PATH (${CONFIG.browserPath}) is not an executable file; falling back to Playwright's bundled Chromium.`);
    return undefined;
  }

  // Install browser if not found
  async installAndStart() {
    console.log('Browser not found or not executable.');
    console.log('Attempting to install Playwright Chromium...');

    try {
      execSync('npx playwright install chromium', {
        stdio: 'inherit',
        timeout: 120000
      });
      console.log('Browser installed successfully.');
      return true;
    } catch (e) {
      console.error('Failed to install browser:', e.message);
      return false;
    }
  }

  async launchContext() {
    const options = {
      headless: CONFIG.headless,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled',
        '--window-size=1920,1080',
        `--remote-debugging-port=${CONFIG.port}`,
      ],
    };
    const executablePath = this.resolveExecutable();
    if (executablePath) options.executablePath = executablePath;
    return chromium.launchPersistentContext(CONFIG.dataDir, options);
  }

  async start() {
    const existing = await probePort(CONFIG.port);
    if (existing) {
      return { success: true, message: 'Browser already running', port: CONFIG.port };
    }

    try {
      console.log('Starting browser...');
      console.log(`Stealth: ${CONFIG.stealth ? 'enabled' : 'disabled'}`);
      console.log(`Mode: ${CONFIG.headless ? 'headless' : 'headed'}`);

      fs.mkdirSync(CONFIG.dataDir, { recursive: true });
      try {
        this.context = await this.launchContext();
      } catch (e) {
        // Playwright's message when the browser binary is missing: "Executable doesn't exist at ..."
        if (/executable.*(doesn't|does not) exist/i.test(e.message)) {
          const installed = await this.installAndStart();
          if (!installed) {
            return {
              success: false,
              error: 'Browser not found and automatic installation failed. Please run: npx playwright install chromium'
            };
          }
          this.context = await this.launchContext();
        } else {
          throw e;
        }
      }

      // Context-level init script covers every page opened later (including by other CLI commands)
      if (CONFIG.stealth) {
        console.log('Applying stealth patch...');
        await this.context.addInitScript(STEALTH_SCRIPT);
      }

      this.page = await this.context.newPage();

      this.saveState('running', { pid: process.pid });
      console.log('Browser started successfully');
      if (CONFIG.stealth) console.log('Stealth patch applied');

      return {
        success: true,
        message: 'Browser started',
        dataDir: CONFIG.dataDir,
        browserPath: CONFIG.browserPath || 'playwright-bundled',
        port: CONFIG.port,
        pid: process.pid,
        stealth: CONFIG.stealth
      };
    } catch (e) {
      console.error('Failed to start browser:', e.message);
      return { success: false, error: e.message };
    }
  }

  // Keep the `start` process alive until the browser closes or we receive SIGINT/SIGTERM
  async waitUntilClosed() {
    if (!this.context) return;
    await new Promise((resolve) => {
      const finish = () => {
        this.saveState('stopped');
        resolve();
      };
      this.context.on('close', finish);
      const shutdown = async () => {
        try { await this.context.close(); } catch (e) {}
        finish();
      };
      process.once('SIGINT', shutdown);
      process.once('SIGTERM', shutdown);
    });
  }

  // Attach to the browser started by `start`. Returns false when none is running.
  async connect() {
    if (this.connected) return true;
    if (!(await probePort(CONFIG.port))) return false;
    try {
      this.browser = await chromium.connectOverCDP(`http://127.0.0.1:${CONFIG.port}`);
      const context = this.browser.contexts()[0];
      if (!context) return false;
      const pages = context.pages();
      if (pages.length) {
        this.page = pages[pages.length - 1];
      } else {
        if (CONFIG.stealth) await context.addInitScript(STEALTH_SCRIPT);
        this.page = await context.newPage();
      }
      this.connected = true;
      return true;
    } catch (e) {
      console.error('Failed to connect to browser:', e.message);
      return false;
    }
  }

  // Drop the CDP connection without closing the browser
  async disconnect() {
    if (this.browser) {
      try { await this.browser.close(); } catch (e) {}
      this.browser = null;
    }
    this.connected = false;
    this.page = null;
  }

  async stop() {
    const alive = await probePort(CONFIG.port);
    if (!alive) {
      this.saveState('stopped');
      return { success: true, message: 'Browser not running' };
    }

    try {
      let closed = false;
      if (await this.connect()) {
        try {
          const session = await this.browser.newBrowserCDPSession();
          await session.send('Browser.close');
          closed = true;
        } catch (e) {
          // Browser.close drops the connection while replying; treat as success if the port goes away
          closed = true;
        }
      }
      for (let i = 0; i < 30 && (await probePort(CONFIG.port)); i++) await sleep(200);

      if (await probePort(CONFIG.port)) {
        const pid = this.readState().pid;
        if (pid) {
          try { process.kill(pid); } catch (e) {}
          for (let i = 0; i < 30 && (await probePort(CONFIG.port)); i++) await sleep(200);
        }
      }
      if (await probePort(CONFIG.port)) {
        return { success: false, error: `Browser on port ${CONFIG.port} did not shut down` };
      }

      this.browser = null;
      this.connected = false;
      this.page = null;
      this.saveState('stopped');
      console.log('Browser closed');
      return { success: true, message: 'Browser closed' };
    } catch (e) {
      console.error('Failed to close browser:', e.message);
      return { success: false, error: e.message };
    }
  }

  async navigate(url) {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      await this.page.goto(url, { waitUntil: 'networkidle' });
      console.log(`Navigated to: ${url}`);
      
      return {
        success: true,
        url,
        title: await this.page.title(),
      };
    } catch (e) {
      console.error(`Navigation failed: ${e.message}`);
      return { success: false, error: e.message };
    }
  }

  async screenshot(outputPath = '/tmp/screenshot.png') {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      // Ensure output directory exists
      const dir = path.dirname(outputPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      await this.page.screenshot({ path: outputPath, fullPage: true });
      const stats = fs.statSync(outputPath);
      console.log(`Screenshot saved: ${outputPath} (${stats.size} bytes)`);
      
      return { 
        success: true, 
        path: outputPath,
        size: stats.size
      };
    } catch (e) {
      console.error(`Screenshot failed: ${e.message}`);
      return { 
        success: false, 
        error: e.message,
        hint: 'Check if browser is running and page is loaded. Try navigating to a page first.'
      };
    }
  }

  async snapshot() {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      // Get AI-readable snapshot
      const title = await this.page.title();
      const url = this.page.url();

      // Extraction logic lives in snapshot-extract.js (shared with offline tests);
      // collectSnapshot is self-contained so Playwright can serialize it into the page.
      const { content, links, interactiveElements } = await this.page.evaluate(collectSnapshot);

      console.log('Snapshot generated');
      return {
        success: true,
        url,
        title,
        content,
        links,
        interactiveElements,
      };
    } catch (e) {
      console.error(`Snapshot failed: ${e.message}`);
      return { success: false, error: e.message };
    }
  }

  async status() {
    const running = await this.connect();
    let url = null;
    let title = null;

    if (running && this.page) {
      try {
        url = this.page.url();
        title = await this.page.title();
      } catch (e) {}
    }

    return {
      success: true,
      running,
      url,
      title,
      browserPath: CONFIG.browserPath || 'playwright-bundled',
      dataDir: CONFIG.dataDir,
      port: CONFIG.port,
      config: CONFIG,
    };
  }

  async analyze(prompt = "Analyze this page") {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      // 1. Take screenshot
      const screenshotPath = path.join(os.tmpdir(), 'screenshot-analysis.png');
      await this.page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`Screenshot saved: ${screenshotPath}`);

      // 2. Check for Gemini API key
      if (!GEMINI_API_KEY) {
        console.log('Gemini API key not configured. Using basic analysis.');
        return {
          success: true,
          prompt,
          analysis: `Screenshot available at: ${screenshotPath}\n\nTo enable AI analysis, set GEMINI_API_KEY environment variable.`,
          screenshot: screenshotPath,
          note: 'GEMINI_API_KEY not set - basic mode'
        };
      }

      // 3. Call Gemini Vision (JavaScript version)
      console.log('AI analyzing...');
      
      const genAI = new GoogleGenerativeAI(GEMINI_API_KEY);
      const model = genAI.getGenerativeModel({ model: GEMINI_MODEL });

      // Read image as base64
      const imageBuffer = fs.readFileSync(screenshotPath);
      const base64Image = imageBuffer.toString('base64');

      const result = await model.generateContent([
        prompt,
        {
          inlineData: {
            data: base64Image,
            mimeType: 'image/png',
          },
        },
      ]);

      const analysis = result.response.text();
      console.log('Analysis complete');
      
      return {
        success: true,
        prompt,
        analysis: analysis.trim(),
        screenshot: screenshotPath
      };
    } catch (e) {
      console.error(`Analysis failed: ${e.message}`);
      return { success: false, error: e.message };
    }
  }

  async evaluate(script) {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      const result = await this.page.evaluate(script);
      return { success: true, result };
    } catch (e) {
      console.error(`Evaluation failed: ${e.message}`);
      return { success: false, error: e.message };
    }
  }

  // NEW: Wait for element to be visible
  async waitForVisible(selector, timeoutMs = 10000) {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      await this.page.waitForSelector(selector, { 
        state: 'visible', 
        timeout: timeoutMs 
      });
      console.log(`Element visible: ${selector}`);
      return { success: true, selector, message: 'Element is visible' };
    } catch (e) {
      console.error(`Wait for visible failed: ${e.message}`);
      return { 
        success: false, 
        error: e.message,
        hint: `Element ${selector} not found or not visible within ${timeoutMs}ms. Use snapshot to check page structure.`
      };
    }
  }

  // NEW: Click element (requires waitForVisible first)
  async click(selector) {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      await this.page.click(selector);
      console.log(`Clicked: ${selector}`);
      return { success: true, selector, message: 'Element clicked' };
    } catch (e) {
      console.error(`Click failed: ${e.message}`);
      return { 
        success: false, 
        error: e.message,
        hint: `Make sure to call waitForVisible("${selector}") first before clicking.`
      };
    }
  }

  // NEW: Type text (requires waitForVisible first)
  async type(selector, text) {
    if (!(await this.connect())) {
      return { success: false, error: NOT_STARTED };
    }

    try {
      await this.page.fill(selector, text);
      console.log(`Typed into: ${selector}`);
      return { success: true, selector, text, message: 'Text entered' };
    } catch (e) {
      console.error(`Type failed: ${e.message}`);
      return { 
        success: false, 
        error: e.message,
        hint: `Make sure to call waitForVisible("${selector}") first before typing.`
      };
    }
  }
}

// CLI Entry Point
async function main() {
  // 版本检查
  try { require("./version-check").checkForUpdate("ythx-101/lobster-browser-tool"); } catch(e) {}

  const args = process.argv.slice(2);
  const command = args[0] || 'status';
  const arg1 = args[1];
  const arg2 = args[2];

  const browser = new BrowserControl();

  switch (command) {
    case 'start':
      console.log('=== Start Browser ===');
      const startResult = await browser.start();
      console.log(JSON.stringify(startResult, null, 2));
      // Stay resident so later commands can attach; exits when the browser closes or on SIGINT/SIGTERM
      await browser.waitUntilClosed();
      break;

    case 'stop':
      console.log('=== Close Browser ===');
      const stopResult = await browser.stop();
      console.log(JSON.stringify(stopResult, null, 2));
      break;

    case 'navigate':
      if (!arg1) {
        console.error('Usage: lobster-browser-tool navigate <url>');
        process.exit(1);
      }
      console.log(`=== Navigate to ${arg1} ===`);
      const navResult = await browser.navigate(arg1);
      console.log(JSON.stringify(navResult, null, 2));
      break;

    case 'screenshot':
      console.log('=== Take Screenshot ===');
      const screenResult = await browser.screenshot(arg1 || '/tmp/screenshot.png');
      console.log(JSON.stringify(screenResult, null, 2));
      break;

    case 'analyze':
      const analyzePrompt = arg1 || 'Analyze this page';
      console.log('=== AI Vision Analysis ===');
      console.log(`Prompt: ${analyzePrompt}`);
      const analyzeResult = await browser.analyze(analyzePrompt);
      console.log(JSON.stringify(analyzeResult, null, 2));
      break;

    case 'snapshot':
      console.log('=== Page Snapshot ===');
      const snapResult = await browser.snapshot();
      console.log(JSON.stringify(snapResult, null, 2));
      break;

    case 'status':
      console.log('=== Browser Status ===');
      const statusResult = await browser.status();
      console.log(JSON.stringify(statusResult, null, 2));
      break;

    case 'eval':
      if (!arg1) {
        console.error('Usage: lobster-browser-tool eval <script>');
        process.exit(1);
      }
      console.log('=== Execute Script ===');
      const evalResult = await browser.evaluate(arg1);
      console.log(JSON.stringify(evalResult, null, 2));
      break;

    // NEW: wait command
    case 'wait':
      if (!arg1) {
        console.error('Usage: lobster-browser-tool wait <selector> [timeoutMs]');
        process.exit(1);
      }
      console.log(`=== Wait for element visible: ${arg1} ===`);
      const waitResult = await browser.waitForVisible(arg1, parseInt(arg2) || 10000);
      console.log(JSON.stringify(waitResult, null, 2));
      break;

    // NEW: click command
    case 'click':
      if (!arg1) {
        console.error('Usage: lobster-browser-tool click <selector>');
        process.exit(1);
      }
      console.log(`=== Click element: ${arg1} ===`);
      const clickResult = await browser.click(arg1);
      console.log(JSON.stringify(clickResult, null, 2));
      break;

    // NEW: type command
    case 'type':
      if (!arg1 || !arg2) {
        console.error('Usage: lobster-browser-tool type <selector> <text>');
        process.exit(1);
      }
      console.log(`=== Type text into: ${arg1} ===`);
      const typeResult = await browser.type(arg1, arg2);
      console.log(JSON.stringify(typeResult, null, 2));
      break;

    case 'setup':
      console.log('=== Install Browser ===');
      try {
        execSync('npx playwright install chromium', { stdio: 'inherit' });
        console.log('Browser installed successfully');
      } catch (e) {
        console.error('Installation failed:', e.message);
        process.exit(1);
      }
      break;

    default:
      console.log('Lobster Browser Tool - Zero-config CLI Browser');
      console.log('');
      console.log('Usage:');
      console.log('  lobster-browser-tool start                   - Start browser');
      console.log('  lobster-browser-tool stop                    - Close browser');
      console.log('  lobster-browser-tool navigate <url>          - Navigate to URL');
      console.log('  lobster-browser-tool screenshot              - Take screenshot');
      console.log('  lobster-browser-tool analyze "<prompt>"      - AI vision analysis');
      console.log('  lobster-browser-tool snapshot                - Get page structure');
      console.log('  lobster-browser-tool status                  - View status');
      console.log('  lobster-browser-tool eval <script>           - Execute JS');
      console.log('  lobster-browser-tool wait <selector>         - Wait for element visible');
      console.log('  lobster-browser-tool click <selector>        - Click element');
      console.log('  lobster-browser-tool type <selector> <text>  - Type text');
      console.log('  lobster-browser-tool setup                   - Install browser');
      console.log('');
      console.log('Examples:');
      console.log('  lobster-browser-tool start');
      console.log('  lobster-browser-tool navigate https://google.com');
      console.log('  lobster-browser-tool wait "#search-button"');
      console.log('  lobster-browser-tool click "#search-button"');
      console.log('  lobster-browser-tool screenshot');
      console.log('  lobster-browser-tool analyze "What is on this page?"');
      console.log('  lobster-browser-tool status');
      console.log('');
      console.log('Environment Variables:');
      console.log('  CHROMIUM_PATH  - Browser path (default: Playwright bundled Chromium)');
      console.log('  GEMINI_API_KEY - Google Gemini API key for AI analysis');
      console.log('  HEADLESS       - Run in headless mode (default: true)');
      console.log('  GEMINI_MODEL   - Gemini model for analyze (default: gemini-flash-latest)');
      console.log('  LOBSTER_DATA_DIR - Browser profile directory (default: ~/.lobster-browser/profile)');
      console.log('  LOBSTER_PORT   - Remote debugging port (default: 18791)');
      console.log('');
      console.log('If executable not found, run: npm run setup');
      break;
  }

  // Detach from the browser (never closes it; use `stop` for that)
  await browser.disconnect();
}

main().catch(e => {
  console.error('Error:', e.message);
  process.exit(1);
});
