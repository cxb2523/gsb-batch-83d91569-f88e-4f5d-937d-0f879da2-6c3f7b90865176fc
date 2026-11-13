import { test } from "node:test";
import assert from "node:assert/strict";

import { registerBatchCollectPanel } from "../src/batch-collect-ui.js";

/* --------------------------------------------------------------------------
   Minimal DOM doubles — only the surface the panel touches.
   -------------------------------------------------------------------------- */

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.className = "";
    this.textContent = "";
    this.type = "";
    this.id = "";
    this.disabled = false;
    this.removed = false;
    this.parent = null;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  append(...nodes) {
    this.children.push(...nodes);
    for (const node of nodes) node.parent = this;
  }
  appendChild(node) {
    this.children.push(node);
    node.parent = this;
    return node;
  }
  replaceChildren(...nodes) {
    this.children = [...nodes];
    for (const node of nodes) node.parent = this;
  }
  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }
  removeEventListener(type) {
    this.listeners.delete(type);
  }
  click() {
    this.listeners.get("click")?.();
  }
  classList = {
    add: name => {
      const set = new Set(this.className.split(/\s+/).filter(Boolean));
      set.add(name);
      this.className = [...set].join(" ");
    },
    contains: name => this.className.split(/\s+/).includes(name),
  };
  remove() {
    this.removed = true;
    // Mimic Element.remove(): detach from the parent container.
    if (this.parent) {
      this.parent.children = this.parent.children.filter(node => node !== this);
      this.parent = null;
    }
  }
  // Test helper: collect rendered text in document order.
  text() {
    const parts = [];
    const walk = node => {
      if (node.textContent && node.children.length === 0) parts.push(node.textContent);
      for (const child of node.children) walk(child);
    };
    walk(this);
    return parts.join(" | ");
  }
  findById(id) {
    let found = null;
    const walk = node => {
      if (node.id === id) found = node;
      for (const child of node.children) walk(child);
    };
    walk(this);
    return found;
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName);
  }
}

function makeCollector(batches) {
  // batches: array of batch objects returned by collectAll() in order.
  let call = 0;
  const results = new Map();
  const success = new Map();
  let lastBatch = null;
  let collecting = false;
  return {
    async collectAll() {
      collecting = true;
      const batch = batches[Math.min(call, batches.length - 1)];
      call += 1;
      lastBatch = batch;
      for (const result of batch.results) {
        results.set(result.profileId, result);
        if (result.ok) {
          success.set(result.profileId, {
            summary: result.summary,
            collectedAt: result.collectedAt,
            profileName: result.profileName,
          });
        }
      }
      await Promise.resolve();
      collecting = false;
      return batch;
    },
    getLastBatch: () => lastBatch,
    getLastResult: id => results.get(id) ?? null,
    getLastSuccess: id => success.get(id) ?? null,
    isCollecting: () => collecting,
  };
}

const batchWithMixedResults = {
  startedAt: 1000,
  finishedAt: 2000,
  total: 2,
  succeeded: 1,
  failed: 1,
  results: [
    {
      profileId: "proxy-a",
      profileName: "Proxy A",
      ok: true,
      collectedAt: 1500,
      summary: { miners: { now: 42 } },
    },
    {
      profileId: "proxy-b",
      profileName: "Proxy B",
      ok: false,
      collectedAt: 1600,
      reason: "Proxy 返回错误：HTTP 503",
    },
  ],
};

test("batch panel renders totals and one row per profile", async () => {
  const documentRef = new FakeDocument();
  const container = new FakeElement("div");
  const notifications = [];
  const collector = makeCollector([batchWithMixedResults]);
  const api = registerBatchCollectPanel({
    documentRef,
    container,
    collector,
    getProfiles: () => [
      { id: "proxy-a", name: "Proxy A" },
      { id: "proxy-b", name: "Proxy B" },
    ],
    getActiveProfileId: () => "proxy-a",
    notify: (message, type) => notifications.push({ message, type }),
  });

  const button = container.findById("batchCollectButton");
  assert.ok(button);
  button.click();
  await Promise.resolve();
  await Promise.resolve();

  const text = container.text();
  assert.match(text, /共 2 个配置，成功 1 个，失败 1 个/);
  assert.match(text, /Proxy A/);
  assert.match(text, /Proxy B/);
  assert.match(text, /HTTP 503/);
  assert.equal(notifications.at(-1).type, "warning");
  assert.equal(button.disabled, false);
  assert.equal(button.getAttribute("aria-busy"), "false");
  api.cleanup();
  assert.equal(container.children.length, 0, "cleanup detaches the panel");
});

test("batch panel highlighted conclusion follows the active profile, never a neighbour's", async () => {
  const documentRef = new FakeDocument();
  const container = new FakeElement("div");
  const collector = makeCollector([batchWithMixedResults]);
  let activeId = "proxy-a";
  const api = registerBatchCollectPanel({
    documentRef,
    container,
    collector,
    getProfiles: () => [
      { id: "proxy-a", name: "Proxy A" },
      { id: "proxy-b", name: "Proxy B" },
    ],
    getActiveProfileId: () => activeId,
    notify: () => {},
  });

  container.findById("batchCollectButton").click();
  await Promise.resolve();
  await Promise.resolve();

  // Active profile A: shows its own success, including its own miner count.
  assert.match(container.text(), /采集成功/);
  assert.match(container.text(), /当前矿工 42 个/);

  // Switch the active profile WITHOUT running a new batch, then re-render.
  // The highlighted conclusion must now be B's failure — A's summary must
  // not be reused for B.
  activeId = "proxy-b";
  api.render();
  const textAfterSwitch = container.text();
  assert.match(textAfterSwitch, /采集失败/);
  assert.match(textAfterSwitch, /HTTP 503/);
  assert.ok(!/当前矿工 42 个/.test(textAfterSwitch), "A's summary must not appear under B");

  // Switch back: A's own conclusion returns.
  activeId = "proxy-a";
  api.render();
  assert.match(container.text(), /当前矿工 42 个/);

  api.cleanup();
});

test("batch panel marks the active profile row and handles a profile never collected", async () => {
  const documentRef = new FakeDocument();
  const container = new FakeElement("div");
  const collector = makeCollector([batchWithMixedResults]);
  let activeId = "proxy-b";
  const api = registerBatchCollectPanel({
    documentRef,
    container,
    collector,
    getProfiles: () => [
      { id: "proxy-a", name: "Proxy A" },
      { id: "proxy-b", name: "Proxy B" },
    ],
    getActiveProfileId: () => activeId,
    notify: () => {},
  });

  await collector.collectAll();
  api.render();

  // Before any batch, a not-yet-collected profile shows an explicit empty state.
  const freshContainer = new FakeElement("div");
  const freshCollector = makeCollector([
    { startedAt: 0, finishedAt: 0, total: 0, succeeded: 0, failed: 0, results: [] },
  ]);
  registerBatchCollectPanel({
    documentRef: new FakeDocument(),
    container: freshContainer,
    collector: {
      ...freshCollector,
      getLastBatch: () => null,
      getLastResult: () => null,
      getLastSuccess: () => null,
      isCollecting: () => false,
    },
    getProfiles: () => [{ id: "proxy-z", name: "Proxy Z" }],
    getActiveProfileId: () => "proxy-z",
    notify: () => {},
  });
  assert.match(freshContainer.text(), /暂无采集结论/);
  api.cleanup();
});

test("batch panel does not register without a container", () => {
  const api = registerBatchCollectPanel({
    documentRef: new FakeDocument(),
    container: null,
    collector: makeCollector([]),
    getProfiles: () => [],
    getActiveProfileId: () => null,
    notify: () => {},
  });
  assert.equal(typeof api.render, "function");
  assert.doesNotThrow(() => api.render());
  assert.doesNotThrow(() => api.cleanup());
});

test("batch panel warns when triggered without an enabled configuration", async () => {
  const documentRef = new FakeDocument();
  const container = new FakeElement("div");
  const notifications = [];
  let collectCalls = 0;
  const collector = {
    async collectAll() {
      collectCalls += 1;
    },
    getLastBatch: () => null,
    getLastResult: () => null,
    getLastSuccess: () => null,
    isCollecting: () => false,
  };
  const api = registerBatchCollectPanel({
    documentRef,
    container,
    collector,
    getProfiles: () => [],
    getActiveProfileId: () => null,
    notify: (message, type) => notifications.push({ message, type }),
    enabled: () => false,
  });
  container.findById("batchCollectButton").click();
  await Promise.resolve();
  assert.equal(collectCalls, 0, "disabled panel must not start a batch");
  assert.equal(notifications[0].type, "warning");
  api.cleanup();
});

test("batch panel shows a preserved prior success when the active profile fails", async () => {
  const documentRef = new FakeDocument();
  const container = new FakeElement("div");
  // Profile B had an earlier success, then a failure in the latest batch.
  const collector = {
    async collectAll() {},
    getLastBatch: () => null,
    getLastResult: id =>
      id === "proxy-b"
        ? { profileId: "proxy-b", profileName: "Proxy B", ok: false, collectedAt: 3000, reason: "采集超时：Proxy 在规定时间内没有响应" }
        : null,
    getLastSuccess: id =>
      id === "proxy-b"
        ? { profileName: "Proxy B", collectedAt: 1000, summary: { miners: { now: 7 } } }
        : null,
    isCollecting: () => false,
  };
  const api = registerBatchCollectPanel({
    documentRef,
    container,
    collector,
    getProfiles: () => [{ id: "proxy-b", name: "Proxy B" }],
    getActiveProfileId: () => "proxy-b",
    notify: () => {},
  });
  api.render();
  const text = container.text();
  assert.match(text, /采集失败/);
  assert.match(text, /超时/);
  assert.match(text, /保留上一次成功结果/);
  api.cleanup();
});
