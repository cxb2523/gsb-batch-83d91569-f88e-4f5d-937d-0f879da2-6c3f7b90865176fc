/**
 * batch-collect-ui.js – Browser panel for the "batch collection" feature.
 *
 * Renders a self-contained card with:
 *   - a "批量采集" button that triggers one batch over every saved profile,
 *   - the most recent batch totals (total / succeeded / failed),
 *   - a prominent conclusion for the *currently active* profile,
 *   - the full per-profile result list retained from the latest batch.
 *
 * Isolation from the single-config dashboard:
 *   - This panel only reads conclusions from the injected collector; it never
 *     calls fetch itself and never mutates the active profile.
 *   - The highlighted conclusion is re-resolved from getActiveProfileId() on
 *     every render, so after switching profiles it always shows that
 *     profile's own result and never another profile's summary.
 *
 * All dynamic content is attached via textContent — no innerHTML — matching
 * the project's XSS baseline. Dependencies are injected so the module can be
 * exercised with a fake document and in-memory collector in node:test.
 */

function formatTime(epochMs) {
  if (!Number.isFinite(epochMs)) return "--";
  try {
    return new Date(epochMs).toLocaleTimeString();
  } catch {
    return "--";
  }
}

/**
 * Minimal DOM helper. Keeps every node creation explicit so no user-controlled
 * string ever passes through an HTML parser.
 */
function createElement(documentRef, tagName, className, textContent) {
  const node = documentRef.createElement(tagName);
  if (className) node.className = className;
  if (textContent !== undefined && textContent !== null) {
    node.textContent = String(textContent);
  }
  return node;
}

/**
 * Register the batch-collection panel into the supplied container.
 *
 * @param {object} args
 * @param {Document} args.documentRef
 * @param {Element}  args.container      Element the panel is appended to.
 * @param {object}   args.collector      Collector created by createBatchCollector().
 * @param {() => Array<{id: string, name: string}>} args.getProfiles
 * @param {() => string | null} args.getActiveProfileId
 * @param {(message: string, type?: string) => void} args.notify
 * @param {() => boolean} [args.enabled]  When false the button is disabled (e.g. no config).
 * @returns {{ cleanup: () => void, render: () => void }}
 */
export function registerBatchCollectPanel({
  documentRef,
  container,
  collector,
  getProfiles,
  getActiveProfileId,
  notify,
  enabled = () => true,
}) {
  if (!container || typeof container.appendChild !== "function") {
    return {
      cleanup() {},
      render() {},
    };
  }

  const panel = createElement(documentRef, "section", "batch-collect-panel");
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-label", "批量采集结果");

  const header = createElement(documentRef, "div", "batch-collect-header");
  const title = createElement(documentRef, "h2", "batch-collect-title", "批量采集所有 Proxy");
  const button = createElement(documentRef, "button", "btn btn-secondary btn-sm", "批量采集");
  button.type = "button";
  button.id = "batchCollectButton";
  button.setAttribute("aria-label", "批量采集所有已保存 Proxy 的监控数据");
  button.setAttribute("aria-busy", "false");
  button.title = "对全部已保存的 Proxy 逐个请求 /1/summary";
  header.append(title, button);

  const summary = createElement(documentRef, "p", "batch-collect-summary", "尚未执行批量采集。");
  summary.setAttribute("role", "status");
  summary.setAttribute("aria-live", "polite");

  // Highlighted conclusion for the currently active profile.
  const current = createElement(documentRef, "div", "batch-collect-current");
  const currentTitle = createElement(documentRef, "div", "batch-collect-current-title", "当前配置的采集结论");
  const currentBody = createElement(documentRef, "div", "batch-collect-current-body");
  current.append(currentTitle, currentBody);

  const list = createElement(documentRef, "ul", "batch-collect-list");

  panel.append(header, summary, current, list);
  container.appendChild(panel);

  let busy = false;

  function renderCurrentConclusion() {
    currentBody.replaceChildren();
    const activeId = getActiveProfileId();
    if (!activeId) {
      currentBody.append(
        createElement(documentRef, "span", "batch-collect-muted", "当前没有可用的 Proxy 配置。"),
      );
      return;
    }

    const result = collector.getLastResult(activeId);
    if (!result) {
      currentBody.append(
        createElement(documentRef, "span", "batch-collect-muted", "该配置尚未参与批量采集，暂无采集结论。"),
      );
      return;
    }

    const dot = createElement(documentRef, "span", `batch-collect-dot ${result.ok ? "is-ok" : "is-failed"}`);
    dot.setAttribute("aria-hidden", "true");
    const label = createElement(
      documentRef,
      "strong",
      "batch-collect-current-label",
      result.ok ? "采集成功" : "采集失败",
    );
    const time = createElement(
      documentRef,
      "span",
      "batch-collect-current-time",
      `采于 ${formatTime(result.collectedAt)}`,
    );
    currentBody.append(dot, label, time);

    if (result.ok) {
      const success = collector.getLastSuccess(activeId);
      const miners = success?.summary?.miners?.now;
      currentBody.append(
        createElement(
          documentRef,
          "span",
          "batch-collect-current-detail",
          Number.isFinite(miners) ? `最近成功摘要：当前矿工 ${miners} 个` : "最近成功摘要已更新",
        ),
      );
    } else {
      // A failed profile still shows its previous good summary, explicitly
      // labelled as an older success — never as the new result.
      const previous = collector.getLastSuccess(activeId);
      currentBody.append(createElement(documentRef, "span", "batch-collect-reason", result.reason || "采集失败"));
      if (previous) {
        currentBody.append(
          createElement(
            documentRef,
            "span",
            "batch-collect-stale",
            `保留上一次成功结果（采于 ${formatTime(previous.collectedAt)}），本次失败未覆盖它。`,
          ),
        );
      }
    }
  }

  function renderResultRows() {
    list.replaceChildren();
    const batch = collector.getLastBatch();
    if (!batch) return;
    const activeId = getActiveProfileId();

    for (const result of batch.results) {
      const item = createElement(documentRef, "li", "batch-collect-item");
      if (result.profileId === activeId) item.classList.add("is-active");

      const dot = createElement(documentRef, "span", `batch-collect-dot ${result.ok ? "is-ok" : "is-failed"}`);
      dot.setAttribute("aria-hidden", "true");
      const name = createElement(
        documentRef,
        "span",
        "batch-collect-item-name",
        `${result.profileName}（${result.profileId}）`,
      );
      const statusText = result.ok
        ? `成功 · 采于 ${formatTime(result.collectedAt)}`
        : `失败 · 采于 ${formatTime(result.collectedAt)} · ${result.reason || "采集失败"}`;
      const status = createElement(
        documentRef,
        "span",
        `batch-collect-item-status ${result.ok ? "is-ok" : "is-failed"}`,
        statusText,
      );
      item.append(dot, name, status);
      list.append(item);
    }
  }

  function render() {
    const batch = collector.getLastBatch();
    if (busy) {
      summary.textContent = "正在批量采集…";
    } else if (!batch) {
      summary.textContent = "尚未执行批量采集。";
    } else if (batch.readError) {
      summary.textContent = `无法读取已保存的配置：${batch.readError}`;
    } else {
      summary.textContent =
        `上一批次：共 ${batch.total} 个配置，成功 ${batch.succeeded} 个，失败 ${batch.failed} 个` +
        `（完成于 ${formatTime(batch.finishedAt)}）。`;
    }
    renderCurrentConclusion();
    renderResultRows();
  }

  const onClick = async () => {
    // Defense in depth: the collector itself dedupes in-flight batches, but a
    // disabled button also gives immediate feedback that triggers are merged.
    if (busy || collector.isCollecting()) return;
    if (!enabled()) {
      notify("请先连接至少一个 Proxy 配置后再批量采集", "warning");
      return;
    }

    busy = true;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "采集中…";
    render();
    try {
      const batch = await collector.collectAll();
      if (batch.readError) {
        notify(batch.readError, "error");
      } else if (batch.failed > 0) {
        notify(`批量采集完成：${batch.succeeded} 个成功，${batch.failed} 个失败`, "warning");
      } else {
        notify(`批量采集完成：全部 ${batch.succeeded} 个配置采集成功`, "success");
      }
    } catch (error) {
      notify(`批量采集失败：${error?.message || "未知错误"}`, "error");
    } finally {
      busy = false;
      button.disabled = false;
      button.setAttribute("aria-busy", "false");
      button.textContent = "批量采集";
      render();
    }
  };

  button.addEventListener("click", onClick);
  render();

  return {
    render,
    cleanup() {
      button.removeEventListener("click", onClick);
      panel.remove();
    },
  };
}
