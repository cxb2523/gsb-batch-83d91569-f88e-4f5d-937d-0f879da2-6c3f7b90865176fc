import { extractAll, type ExtractedData } from "../lib/extract.ts";
import {
  saveScan,
  upsertEmail,
  getEmails,
  getSettings,
  saveSettings,
} from "../lib/storage.ts";
import { enrichEmail } from "../lib/intelligence.ts";
import {
  guessEmailPatterns,
  generateRoleAddresses,
  detectLinkedPages,
  fetchGitHubEmails,
} from "../lib/discovery.ts";
import {
  toCSV,
  toJSON,
  toTabSeparated,
  toVCard,
  downloadBlob,
  urlsToTxt,
  urlsToCsv,
  urlsToJson,
} from "../lib/export.ts";
import {
  extractSocialLinks,
  classifyPage,
  detectRelatedPages,
  fetchDomainInfo,
} from "../lib/page-intelligence.ts";
import type {
  EmailRecord,
  UrlCandidateRecord,
  UrlCandidateStatus,
  UrlRecord,
  UrlSettings,
  UrlSortMode,
  UrlSourceMode,
  UrlVisibilityMode,
} from "../lib/schemas.ts";
import { sortUrls } from "../lib/url-extract.ts";
import log from "../lib/logger.ts";

const runBtn = document.getElementById("run") as HTMLButtonElement;
const outEl = document.getElementById("out") as HTMLPreElement;
const resultsEl = document.getElementById("results") as HTMLDivElement;
const countEl = document.getElementById("count") as HTMLSpanElement;
const copyBtn = document.getElementById("copy") as HTMLButtonElement;
const modeSelect = document.getElementById("mode") as HTMLSelectElement;
const extrasEl = document.getElementById("extras") as HTMLDivElement;
const dashboardBtn = document.getElementById("dashboard") as HTMLButtonElement;

let lastResult: ExtractedData = { emails: [], phones: [], socialUrls: [] };

runBtn.addEventListener("click", async () => {
  runBtn.classList.add("loading");
  runBtn.textContent = "Scanning\u2026";

  const mode = modeSelect.value as "text" | "html";
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });

  if (!tab?.id) {
    showError("No active tab found.");
    resetButton();
    return;
  }

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        html: document.documentElement.innerHTML,
        text: document.body.innerText,
      }),
    });

    const pageData = results[0]?.result;
    if (!pageData) {
      showError("Cannot access this page.");
      resetButton();
      return;
    }

    lastResult = extractAll({
      mode,
      html: pageData.html,
      text: pageData.text,
    });

    resultsEl.classList.add("visible");

    if (lastResult.emails.length > 0) {
      countEl.textContent = `${lastResult.emails.length} email${lastResult.emails.length > 1 ? "s" : ""} found`;
      outEl.textContent = lastResult.emails.join("\n");
      outEl.classList.remove("empty");
      copyBtn.style.display = "";
    } else {
      countEl.textContent = "";
      outEl.textContent = "No emails found on this page.";
      outEl.classList.add("empty");
      copyBtn.style.display = "none";
    }

    // Update badge
    chrome.runtime
      .sendMessage({
        type: "UPDATE_BADGE",
        tabId: tab.id,
        count: lastResult.emails.length,
      })
      .catch((error: unknown) => log.warn("Badge message failed:", error));

    // Auto-save scan + emails
    const sourceUrl = tab.url ?? "";
    const now = Date.now();

    saveScan({
      id: `${now}-${Math.random().toString(36).slice(2, 8)}`,
      url: sourceUrl,
      timestamp: now,
      emailCount: lastResult.emails.length,
      emails: lastResult.emails,
    }).catch((error: unknown) => log.warn("Failed to save scan:", error));

    // Enrich and save emails (async, non-blocking)
    // Sequential: enrichment hits external APIs, parallelizing could rate-limit
    (async () => {
      for (const email of lastResult.emails) {
        try {
          const domain = email.split("@")[1] ?? "";
          const enrichment = await enrichEmail(email, 1);
          await upsertEmail({
            email,
            domain,
            firstSeen: now,
            lastSeen: now,
            sourceUrls: sourceUrl ? [sourceUrl] : [],
            tags: [],
            notes: "",
            starred: false,
            type: enrichment.type,
            provider: enrichment.provider,
            confidence: enrichment.confidence,
            mxValid: enrichment.mxValid,
          });
        } catch (error) {
          log.warn("Failed to enrich/save email:", error);
        }
      }
    })().catch((error: unknown) =>
      log.warn("Enrichment pipeline failed:", error),
    );

    renderExtras();
  } catch {
    showError("Cannot access this page.");
  }

  resetButton();
});

copyBtn.addEventListener("click", () => {
  if (lastResult.emails.length === 0) {
    return;
  }
  navigator.clipboard
    .writeText(lastResult.emails.join("\n"))
    .catch((error: unknown) => log.warn("Clipboard write failed:", error));
  copyBtn.textContent = "Copied!";
  copyBtn.classList.add("copied");
  setTimeout(() => {
    copyBtn.textContent = "Copy";
    copyBtn.classList.remove("copied");
  }, 1200);
});

const exportSelect = document.getElementById(
  "export-format",
) as HTMLSelectElement;

exportSelect.addEventListener("change", () => {
  const format = exportSelect.value;
  if (lastResult.emails.length === 0 || !format) {
    return;
  }

  getEmails()
    .then((storedEmails) => {
      const storedMap = new Map(storedEmails.map((r) => [r.email, r]));
      const now = Date.now();

      const records: EmailRecord[] = lastResult.emails.map((email) => {
        const stored = storedMap.get(email);
        if (stored) {
          return stored;
        }
        return {
          email,
          domain: email.split("@")[1] ?? "",
          firstSeen: now,
          lastSeen: now,
          sourceUrls: [],
          tags: [],
          notes: "",
          starred: false,
          type: "personal" as const,
          provider: "custom" as const,
          confidence: 50,
          mxValid: null,
        };
      });

      switch (format) {
        case "csv":
          downloadBlob(toCSV(records), "trawl-export.csv", "text/csv");
          break;
        case "json":
          downloadBlob(
            toJSON(records),
            "trawl-export.json",
            "application/json",
          );
          break;
        case "tsv":
          navigator.clipboard
            .writeText(toTabSeparated(records))
            .catch((error: unknown) =>
              log.warn("Clipboard write failed:", error),
            );
          break;
        case "vcard":
          downloadBlob(toVCard(records), "trawl-export.vcf", "text/vcard");
          break;
        default:
          break;
      }
    })
    .catch((error: unknown) =>
      log.warn("Failed to load records for export:", error),
    );

  // Reset select
  exportSelect.value = "";
});

dashboardBtn.addEventListener("click", () => {
  chrome.tabs
    .create({
      url: chrome.runtime.getURL("src/dashboard/dashboard.html"),
    })
    .catch((error: unknown) => log.warn("Failed to open dashboard:", error));
});

function showError(message: string): void {
  resultsEl.classList.add("visible");
  countEl.textContent = "";
  outEl.textContent = message;
  outEl.classList.add("empty");
  copyBtn.style.display = "none";
}

function resetButton(): void {
  runBtn.classList.remove("loading");
  runBtn.textContent = "Collect";
}

function createExtrasSection(title: string, items: string[]): HTMLElement {
  const details = document.createElement("details");
  details.className = "extras-section";

  const summary = document.createElement("summary");
  summary.textContent = `${title} (${items.length})`;
  details.append(summary);

  const pre = document.createElement("pre");
  pre.textContent = items.join("\n");
  details.append(pre);

  return details;
}

function renderExtras(): void {
  extrasEl.replaceChildren();

  if (lastResult.phones.length > 0) {
    extrasEl.append(createExtrasSection("Phone numbers", lastResult.phones));
  }

  if (lastResult.socialUrls.length > 0) {
    extrasEl.append(
      createExtrasSection("Social profiles", lastResult.socialUrls),
    );
  }
}

// Discovery panel
const discGuessBtn = document.getElementById("disc-guess") as HTMLButtonElement;
const discGuessOut = document.getElementById(
  "disc-guess-out",
) as HTMLPreElement;
const discFirstInput = document.getElementById(
  "disc-first",
) as HTMLInputElement;
const discLastInput = document.getElementById("disc-last") as HTMLInputElement;
const discRolesBtn = document.getElementById("disc-roles") as HTMLButtonElement;
const discRolesOut = document.getElementById(
  "disc-roles-out",
) as HTMLPreElement;
const discLinksBtn = document.getElementById("disc-links") as HTMLButtonElement;
const discLinksOut = document.getElementById(
  "disc-links-out",
) as HTMLPreElement;
const discGithubBtn = document.getElementById(
  "disc-github-btn",
) as HTMLButtonElement;
const discGithubInput = document.getElementById(
  "disc-github",
) as HTMLInputElement;
const discGithubOut = document.getElementById(
  "disc-github-out",
) as HTMLPreElement;

async function getCurrentDomain(): Promise<string> {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab?.url) {
    return "";
  }
  try {
    return new URL(tab.url).hostname;
  } catch {
    return "";
  }
}

discGuessBtn.addEventListener("click", async () => {
  const firstName = discFirstInput.value.trim();
  const lastName = discLastInput.value.trim();
  const domain = await getCurrentDomain();
  if (!firstName || !lastName || !domain) {
    discGuessOut.textContent =
      "Enter first & last name. Domain from current tab.";
    return;
  }
  const patterns = guessEmailPatterns(firstName, lastName, domain);
  discGuessOut.textContent = patterns.join("\n");
});

discRolesBtn.addEventListener("click", async () => {
  const domain = await getCurrentDomain();
  if (!domain) {
    discRolesOut.textContent = "No domain detected.";
    return;
  }
  const roles = generateRoleAddresses(domain);
  discRolesOut.textContent = roles.join("\n");
});

discLinksBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab?.id || !tab.url) {
    discLinksOut.textContent = "No active tab.";
    return;
  }

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => document.documentElement.innerHTML,
    });
    const html = results[0]?.result ?? "";
    const links = detectLinkedPages(html, tab.url);
    discLinksOut.textContent =
      links.length > 0
        ? links.join("\n")
        : "No contact/about/team pages found.";
  } catch {
    discLinksOut.textContent = "Cannot access this page.";
  }
});

discGithubBtn.addEventListener("click", async () => {
  const username = discGithubInput.value.trim();
  if (!username) {
    discGithubOut.textContent = "Enter a GitHub username.";
    return;
  }
  discGithubOut.textContent = "Fetching...";
  const emails = await fetchGitHubEmails(username);
  discGithubOut.textContent =
    emails.length > 0 ? emails.join("\n") : "No public emails found.";
});

// Page intelligence panel
const pageTypeEl = document.getElementById("page-type") as HTMLSpanElement;
const pageSocialEl = document.getElementById("page-social") as HTMLPreElement;
const pageRelatedEl = document.getElementById("page-related") as HTMLPreElement;
const pageWhoisBtn = document.getElementById(
  "page-whois-btn",
) as HTMLButtonElement;
const pageWhoisEl = document.getElementById("page-whois") as HTMLPreElement;

// Auto-populate page intelligence when panel opens
const pageIntelPanel = document.getElementById(
  "page-intel-panel",
) as HTMLDetailsElement;

pageIntelPanel.addEventListener("toggle", async () => {
  if (!pageIntelPanel.open) {
    return;
  }

  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab?.id || !tab.url) {
    return;
  }

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => document.documentElement.innerHTML,
    });
    const html = results[0]?.result ?? "";

    // Page type
    const pageType = classifyPage(tab.url, html);
    pageTypeEl.textContent = pageType;

    // Social links
    const socialLinks = extractSocialLinks(html);
    pageSocialEl.textContent =
      socialLinks.length > 0
        ? socialLinks.map((l) => `${l.platform}: ${l.url}`).join("\n")
        : "No social links found.";

    // Related pages
    const related = detectRelatedPages(html, tab.url);
    pageRelatedEl.textContent =
      related.length > 0 ? related.join("\n") : "No related pages found.";
  } catch {
    pageTypeEl.textContent = "unavailable";
  }
});

pageWhoisBtn.addEventListener("click", async () => {
  const domain = await getCurrentDomain();
  if (!domain) {
    pageWhoisEl.textContent = "No domain detected.";
    return;
  }
  pageWhoisEl.textContent = "Looking up...";
  const info = await fetchDomainInfo(domain);
  const lines = [
    `Domain: ${info.domain}`,
    `Registrar: ${info.registrar ?? "unknown"}`,
    `Created: ${info.creationDate ?? "unknown"}`,
    `Expires: ${info.expiryDate ?? "unknown"}`,
  ];
  pageWhoisEl.textContent = lines.join("\n");
});

// Settings panel
const autoScanToggle = document.getElementById(
  "auto-scan-toggle",
) as HTMLInputElement;
const allowlistEl = document.getElementById("allowlist") as HTMLTextAreaElement;
const blocklistEl = document.getElementById("blocklist") as HTMLTextAreaElement;

function parseDomainList(text: string): string[] {
  return text
    .split("\n")
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean);
}

// Load settings on popup open
(async () => {
  const settings = await getSettings();
  autoScanToggle.checked = settings.autoScan;
  allowlistEl.value = settings.allowlist.join("\n");
  blocklistEl.value = settings.blocklist.join("\n");
})().catch((error: unknown) => log.warn("Failed to load settings:", error));

autoScanToggle.addEventListener("change", async () => {
  const s = await getSettings();
  s.autoScan = autoScanToggle.checked;
  await saveSettings(s);
});

allowlistEl.addEventListener("change", async () => {
  const s = await getSettings();
  s.allowlist = parseDomainList(allowlistEl.value);
  await saveSettings(s);
});

blocklistEl.addEventListener("change", async () => {
  const s = await getSettings();
  s.blocklist = parseDomainList(blocklistEl.value);
  await saveSettings(s);
});

// =============================================================================
// URLs section
// =============================================================================

const urlsCountEl = document.getElementById("urls-count") as HTMLSpanElement;
const urlsRunBtn = document.getElementById("urls-run") as HTMLButtonElement;
const urlsSortAlphaBtn = document.getElementById(
  "urls-sort-alpha",
) as HTMLButtonElement;
const urlsSortPageBtn = document.getElementById(
  "urls-sort-page",
) as HTMLButtonElement;
const urlsFilterToggleBtn = document.getElementById(
  "urls-filter-toggle",
) as HTMLButtonElement;
const urlsFiltersEl = document.getElementById("urls-filters") as HTMLDivElement;
const urlsVisibilitySelect = document.getElementById(
  "urls-visibility",
) as HTMLSelectElement;
const urlsSourceSelect = document.getElementById(
  "urls-source",
) as HTMLSelectElement;
const urlsCopyBtn = document.getElementById("urls-copy") as HTMLButtonElement;
const urlsExportSelect = document.getElementById(
  "urls-export",
) as HTMLSelectElement;
const urlsListEl = document.getElementById("urls-list") as HTMLDivElement;
const urlsEmptyEl = document.getElementById("urls-empty") as HTMLDivElement;
const urlsTraceHeadEl = document.getElementById(
  "urls-trace-head",
) as HTMLDivElement;
const urlsTraceToggleBtn = document.getElementById(
  "urls-trace-toggle",
) as HTMLButtonElement;
const urlsTraceSummaryEl = document.getElementById(
  "urls-trace-summary",
) as HTMLSpanElement;
const urlsTraceFiltersEl = document.getElementById(
  "urls-trace-filters",
) as HTMLDivElement;
const urlsTraceEl = document.getElementById("urls-trace") as HTMLDivElement;

let urlsLastResult: UrlRecord[] = [];
let urlsLastCandidates: UrlCandidateRecord[] = [];
let urlsHasRun = false;
const urlsTraceStatusFilter = new Set<UrlCandidateStatus>();
let urlsTraceOpen = false;
let urlsCurrentSettings: UrlSettings = {
  visibilityMode: "visible",
  sourceMode: "comprehensive",
  sortMode: "alpha",
};

const URL_STATUS_META: Record<
  UrlCandidateStatus,
  { label: string; title: string }
> = {
  included: { label: "Included", title: "Collected into the result list" },
  duplicate: { label: "Duplicate", title: "Repeated normalized URL" },
  parseFailed: {
    label: "Parse failed",
    title: "Empty, unparseable or non-http(s)",
  },
  sourceDisabled: {
    label: "Source disabled",
    title: "Source not enabled by the current Sources mode",
  },
  skipped: {
    label: "Skipped",
    title: "Inside <head>; requires Everything mode",
  },
  invisible: { label: "Invisible", title: "Failed the visibility filter" },
};

const URL_SOURCE_LABELS: Record<UrlCandidateRecord["sourceCategory"], string> =
  {
    anchor: "anchor",
    area: "area",
    media: "media",
    text: "text",
    head: "head",
    script: "script",
    meta: "meta",
  };

function applySortButtonsActive(mode: UrlSortMode): void {
  urlsSortAlphaBtn.classList.toggle("active", mode === "alpha");
  urlsSortPageBtn.classList.toggle("active", mode === "pageOrder");
}

function renderUrlsList(): void {
  const sorted = sortUrls(urlsLastResult, urlsCurrentSettings.sortMode);
  urlsListEl.replaceChildren();
  if (sorted.length === 0) {
    urlsListEl.hidden = true;
    urlsEmptyEl.hidden = false;
    urlsEmptyEl.textContent =
      urlsLastResult.length === 0
        ? "Click Extract to scan this page."
        : "No URLs match the current filter.";
    return;
  }
  urlsEmptyEl.hidden = true;
  urlsListEl.hidden = false;

  for (const record of sorted) {
    const row = document.createElement("div");
    row.className = "urls-row";

    const link = document.createElement("a");
    link.className = "urls-row-link";
    link.href = record.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = record.url;
    link.textContent = record.url;
    row.append(link);

    if (record.count > 1) {
      const countSpan = document.createElement("span");
      countSpan.className = "urls-row-count";
      countSpan.textContent = `\u00d7${record.count}`;
      row.append(countSpan);
    }

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "urls-row-copy";
    copyBtn.title = "Copy this URL";
    copyBtn.textContent = "\u29c9";
    copyBtn.addEventListener("click", (event) => {
      event.preventDefault();
      navigator.clipboard
        .writeText(record.url)
        .catch((err: unknown) => log.warn("URL copy failed:", err));
      copyBtn.classList.add("copied");
      setTimeout(() => copyBtn.classList.remove("copied"), 1000);
    });
    row.append(copyBtn);

    urlsListEl.append(row);
  }
}

function renderUrlsHeader(): void {
  urlsCountEl.textContent =
    urlsLastResult.length > 0 ? String(urlsLastResult.length) : "";
}

function countCandidatesByStatus(): Map<UrlCandidateStatus, number> {
  const counts = new Map<UrlCandidateStatus, number>();
  for (const candidate of urlsLastCandidates) {
    counts.set(candidate.status, (counts.get(candidate.status) ?? 0) + 1);
  }
  return counts;
}

function renderUrlsTraceSummary(): void {
  const counts = countCandidatesByStatus();
  const parts: string[] = [];
  for (const status of Object.keys(URL_STATUS_META) as UrlCandidateStatus[]) {
    const n = counts.get(status);
    if (n !== undefined) {
      parts.push(`${n} ${URL_STATUS_META[status].label.toLowerCase()}`);
    }
  }
  urlsTraceSummaryEl.textContent =
    parts.length > 0 ? parts.join(" · ") : "No candidates";
}

function renderUrlsTraceFilters(): void {
  const counts = countCandidatesByStatus();
  urlsTraceFiltersEl.replaceChildren();
  for (const status of Object.keys(URL_STATUS_META) as UrlCandidateStatus[]) {
    const n = counts.get(status) ?? 0;
    if (n === 0) {
      continue;
    }
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `urls-trace-chip urls-status-${status}`;
    chip.classList.toggle("active", urlsTraceStatusFilter.has(status));
    chip.title = URL_STATUS_META[status].title;
    chip.textContent = `${URL_STATUS_META[status].label} (${n})`;
    chip.addEventListener("click", () => {
      if (urlsTraceStatusFilter.has(status)) {
        urlsTraceStatusFilter.delete(status);
      } else {
        urlsTraceStatusFilter.add(status);
      }
      renderUrlsTraceFilters();
      renderUrlsTrace();
    });
    urlsTraceFiltersEl.append(chip);
  }
}

function renderUrlsTrace(): void {
  urlsTraceEl.replaceChildren();

  if (urlsLastCandidates.length === 0) {
    const empty = document.createElement("div");
    empty.className = "urls-trace-empty empty";
    empty.textContent =
      "No URL candidates were found on this page for the current sources.";
    urlsTraceEl.append(empty);
    return;
  }

  const visible = urlsLastCandidates.filter(
    (candidate) =>
      urlsTraceStatusFilter.size === 0 ||
      urlsTraceStatusFilter.has(candidate.status),
  );

  if (visible.length === 0) {
    const empty = document.createElement("div");
    empty.className = "urls-trace-empty empty";
    empty.textContent = "No candidates match the selected status filters.";
    urlsTraceEl.append(empty);
    return;
  }

  // Candidates are already stored in page order.
  for (const candidate of visible) {
    const row = document.createElement("div");
    row.className = `urls-trace-row urls-status-${candidate.status}`;

    const badge = document.createElement("span");
    badge.className = "urls-trace-badge";
    badge.textContent = URL_STATUS_META[candidate.status].label;
    row.append(badge);

    const source = document.createElement("span");
    source.className = "urls-trace-source";
    source.textContent = URL_SOURCE_LABELS[candidate.sourceCategory];
    source.title = "Source category";
    row.append(source);

    const body = document.createElement("div");
    body.className = "urls-trace-body";

    const valueLine = document.createElement("div");
    valueLine.className = "urls-trace-value";
    if (candidate.status === "included" && candidate.url !== null) {
      const link = document.createElement("a");
      link.href = candidate.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = candidate.url;
      valueLine.append(link);
    } else {
      valueLine.textContent = candidate.rawValue || "(empty)";
    }
    body.append(valueLine);

    const metaLine = document.createElement("div");
    metaLine.className = "urls-trace-meta";
    const metaParts = [candidate.reason];
    if (candidate.occurrence > 1) {
      metaParts.push(`occurrence #${candidate.occurrence}`);
    }
    metaLine.textContent = metaParts.join(" · ");
    body.append(metaLine);

    row.append(body);
    urlsTraceEl.append(row);
  }
}

function renderUrlsTracePanel(): void {
  const hasRun = urlsHasRun;
  urlsTraceHeadEl.hidden = !hasRun;
  renderUrlsTraceSummary();
  renderUrlsTraceFilters();
  if (!hasRun) {
    urlsTraceEl.hidden = true;
    urlsTraceOpen = false;
    urlsTraceToggleBtn.setAttribute("aria-expanded", "false");
    return;
  }
  urlsTraceEl.hidden = !urlsTraceOpen;
  urlsTraceToggleBtn.setAttribute(
    "aria-expanded",
    urlsTraceOpen ? "true" : "false",
  );
  renderUrlsTrace();
}

urlsTraceToggleBtn.addEventListener("click", () => {
  urlsTraceOpen = !urlsTraceOpen;
  renderUrlsTracePanel();
});

async function persistUrlSettings(): Promise<void> {
  const s = await getSettings();
  s.url = urlsCurrentSettings;
  await saveSettings(s);
}

async function runUrlExtraction(): Promise<void> {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab?.id) {
    urlsEmptyEl.hidden = false;
    urlsEmptyEl.textContent = "No active tab.";
    return;
  }
  urlsRunBtn.classList.add("loading");
  urlsRunBtn.textContent = "Scanning\u2026";
  try {
    const response = (await chrome.tabs.sendMessage(tab.id, {
      type: "EXTRACT_URLS",
      visibilityMode: urlsCurrentSettings.visibilityMode,
      sourceMode: urlsCurrentSettings.sourceMode,
    })) as { urls: UrlRecord[]; candidates?: UrlCandidateRecord[] } | undefined;
    urlsLastResult = response?.urls ?? [];
    urlsLastCandidates = response?.candidates ?? [];
    urlsHasRun = true;
    urlsTraceStatusFilter.clear();
  } catch (err) {
    log.warn("URL extraction failed:", err);
    urlsLastResult = [];
    urlsLastCandidates = [];
    urlsHasRun = true;
    urlsTraceStatusFilter.clear();
    urlsEmptyEl.hidden = false;
    urlsEmptyEl.textContent =
      "Cannot access this page. Reload the tab and try again.";
  }
  urlsRunBtn.classList.remove("loading");
  urlsRunBtn.textContent = "Extract";
  renderUrlsHeader();
  renderUrlsList();
  renderUrlsTracePanel();
}

urlsRunBtn.addEventListener("click", () => {
  runUrlExtraction().catch((err: unknown) =>
    log.warn("URL run handler failed:", err),
  );
});

urlsSortAlphaBtn.addEventListener("click", () => {
  urlsCurrentSettings = { ...urlsCurrentSettings, sortMode: "alpha" };
  applySortButtonsActive("alpha");
  renderUrlsList();
  persistUrlSettings().catch((err: unknown) =>
    log.warn("Persist sort failed:", err),
  );
});

urlsSortPageBtn.addEventListener("click", () => {
  urlsCurrentSettings = { ...urlsCurrentSettings, sortMode: "pageOrder" };
  applySortButtonsActive("pageOrder");
  renderUrlsList();
  persistUrlSettings().catch((err: unknown) =>
    log.warn("Persist sort failed:", err),
  );
});

urlsFilterToggleBtn.addEventListener("click", () => {
  const willOpen = urlsFiltersEl.hidden as boolean;
  urlsFiltersEl.hidden = !willOpen;
  urlsFilterToggleBtn.classList.toggle("active", willOpen);
});

urlsVisibilitySelect.addEventListener("change", () => {
  urlsCurrentSettings = {
    ...urlsCurrentSettings,
    visibilityMode: urlsVisibilitySelect.value as UrlVisibilityMode,
  };
  persistUrlSettings()
    .then(() => runUrlExtraction())
    .catch((err: unknown) =>
      log.warn("Persist+rerun (visibility) failed:", err),
    );
});

urlsSourceSelect.addEventListener("change", () => {
  urlsCurrentSettings = {
    ...urlsCurrentSettings,
    sourceMode: urlsSourceSelect.value as UrlSourceMode,
  };
  persistUrlSettings()
    .then(() => runUrlExtraction())
    .catch((err: unknown) => log.warn("Persist+rerun (source) failed:", err));
});

urlsCopyBtn.addEventListener("click", () => {
  if (urlsLastResult.length === 0) {
    return;
  }
  const sorted = sortUrls(urlsLastResult, urlsCurrentSettings.sortMode);
  navigator.clipboard
    .writeText(sorted.map((r) => r.url).join("\n"))
    .catch((err: unknown) => log.warn("URL copy-all failed:", err));
  urlsCopyBtn.textContent = "Copied!";
  urlsCopyBtn.classList.add("copied");
  setTimeout(() => {
    urlsCopyBtn.textContent = "Copy";
    urlsCopyBtn.classList.remove("copied");
  }, 1200);
});

urlsExportSelect.addEventListener("change", () => {
  const format = urlsExportSelect.value;
  if (urlsLastResult.length === 0 || !format) {
    urlsExportSelect.value = "";
    return;
  }
  const sorted = sortUrls(urlsLastResult, urlsCurrentSettings.sortMode);
  switch (format) {
    case "txt":
      downloadBlob(urlsToTxt(sorted), "trawl-urls.txt", "text/plain");
      break;
    case "csv":
      downloadBlob(urlsToCsv(sorted), "trawl-urls.csv", "text/csv");
      break;
    case "json":
      downloadBlob(urlsToJson(sorted), "trawl-urls.json", "application/json");
      break;
    default:
      break;
  }
  urlsExportSelect.value = "";
});

(async () => {
  const settings = await getSettings();
  urlsCurrentSettings = settings.url;
  urlsVisibilitySelect.value = urlsCurrentSettings.visibilityMode;
  urlsSourceSelect.value = urlsCurrentSettings.sourceMode;
  applySortButtonsActive(urlsCurrentSettings.sortMode);
  urlsEmptyEl.hidden = false;
  urlsListEl.hidden = true;
  urlsTraceHeadEl.hidden = true;
  urlsTraceEl.hidden = true;
})().catch((err: unknown) => log.warn("Failed to load URL settings:", err));
