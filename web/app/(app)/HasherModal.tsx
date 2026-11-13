"use client";

import { useRef, useState } from "react";
import { useCart } from "./CartContext";
import { downloadGame } from "./download";
import { BoltIcon, CheckCircleIcon, CheckIcon, ShieldCheckIcon, TrashIcon, UploadIcon, WarningIcon } from "./icons";
import { computeRaHash } from "./raHash";
import { lookupHash } from "./verifyHash";
import type { SearchResult } from "./types";
import { useLocale } from "./useLocale";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = -1;
  do {
    value /= 1024;
    unitIndex++;
  } while (value >= 1024 && unitIndex < units.length - 1);
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

export default function HasherModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useLocale();
  const cart = useCart();
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hash, setHash] = useState("");
  const [consoleGuess, setConsoleGuess] = useState("");
  const [fileInfo, setFileInfo] = useState<{ name: string; size: number } | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  function reset() {
    setError("");
    setHash("");
    setConsoleGuess("");
    setFileInfo(null);
    setResult(null);
  }

  async function handleFile(file: File) {
    reset();
    setFileInfo({ name: file.name, size: file.size });
    const buffer = new Uint8Array(await file.arrayBuffer());
    const computed = computeRaHash(file.name, buffer);
    if ("error" in computed) {
      setError(computed.error);
      return;
    }
    setHash(computed.hash);
    setConsoleGuess(computed.consoleGuess);

    setLoading(true);
    try {
      const data = await lookupHash(computed.hash);
      if (data.success) setResult(data);
      else setError(data.message || t("common.hashNotFound"));
    } catch {
      setError(t("common.hashVerifyFailed"));
    } finally {
      setLoading(false);
    }
  }

  function addToCart() {
    if (!result) return;
    cart.add({
      id: hash,
      name: result.name ?? hash,
      consoles: result.console ? [result.console] : [],
      image_icon: null,
      achievements: null,
      hash,
      rom_path: "",
    });
  }

  const fullyVerified = !!result?.ra_recognized && !!result?.link_ok;

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          reset();
          onClose();
        }
      }}
    >
      <div className="modal-panel">
        <div className="modal-head">
          <h2>
            {t("topbar.verifyRom")} <CheckCircleIcon className="title-badge" />
          </h2>
          <button
            type="button"
            className="modal-close"
            onClick={() => {
              reset();
              onClose();
            }}
            aria-label={t("common.close")}
          >
            &times;
          </button>
        </div>
        <div className="modal-body">
          {!result && (
            <div
              className={`hasher-dropzone${dragOver ? " drag-over" : ""}`}
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files[0];
                if (file) void handleFile(file);
              }}
            >

              <h3>{t("hasher.dropTitle")}</h3>
              <p className="hasher-dropzone-sub">{t("hasher.dropSub")}</p>
              <button
                type="button"
                className="btn-ghost hasher-select-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  inputRef.current?.click();
                }}
              >
                <UploadIcon size={14} />
                <span>{t("hasher.selectFile")}</span>
              </button>
              <div className="hasher-badges">
                {[".zip", "NES", "SNES", "GBA", "N64", "Genesis"].map((label) => (
                  <span key={label} className="hasher-badge">
                    {label}
                  </span>
                ))}
              </div>
              <input
                ref={inputRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleFile(file);
                  e.target.value = "";
                }}
              />
            </div>
          )}

          <div className="hasher-note">
            <ShieldCheckIcon />
            <span>{t("hasher.note")}</span>
          </div>
          <p className="hasher-disc-note">
            {t("hasher.discNote1")}
            <a
              href="https://github.com/Siallus/RetroAchievementsLibraryValidator"
              target="_blank"
              rel="noopener"
              style={{ color: "var(--link)" }}
            >
              RetroAchievementsLibraryValidator
            </a>
            {t("hasher.discNote2")}
          </p>

          {loading && <p className="empty-hint">{t("common.verifyingHash")}</p>}
          {error && <p className="empty-hint">{error}</p>}

          {result && (
            <div className={`hasher-result ${fullyVerified ? "ok" : "warn"}`}>
              <div className="hasher-result-title">
                {fullyVerified ? <CheckCircleIcon /> : <WarningIcon />}
                {fullyVerified ? t("hasher.recognized") : t("hasher.found")}
              </div>

              <div className="hasher-result-grid">
                <div>
                  <h4>{t("hasher.localFile")}</h4>
                  <dl>
                    <div>
                      <dt>{t("hasher.name")}</dt> <dd>{fileInfo?.name ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>{t("hasher.size")}</dt> <dd>{fileInfo ? formatBytes(fileInfo.size) : "—"}</dd>
                    </div>
                    <div>
                      <dt>{t("hasher.hashMd5")}</dt> <dd className="mono">{hash}</dd>
                    </div>
                  </dl>
                </div>
                <div>
                  <h4>RetroAchievements</h4>
                  <dl>
                    <div>
                      <dt>{t("hasher.game")}</dt> <dd>{result.name ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>{t("hasher.platform")}</dt> <dd>{result.console ?? consoleGuess}</dd>
                    </div>
                    <div>
                      <dt>{t("hasher.recognizedLabel")}</dt> <dd>{result.ra_recognized ? t("hasher.yes") : t("hasher.no")}</dd>
                    </div>
                    <div>
                      <dt>{t("hasher.link")}</dt> <dd>{result.link_ok ? t("hasher.verified") : t("hasher.notVerified")}</dd>
                    </div>
                  </dl>
                </div>
              </div>

              <div className="hasher-result-actions">
                <button type="button" className="btn-ghost" onClick={() => downloadGame(hash, result.name)}>
                  <BoltIcon /> {t("common.download")}
                </button>
                <button type="button" className="btn-ghost" disabled={cart.has(hash)} onClick={addToCart}>
                  {cart.has(hash) ? (
                    <span key="added" className="icon-pop" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <CheckIcon /> {t("common.inCart")}
                    </span>
                  ) : (
                    t("common.addToCart")
                  )}
                </button>
                <button type="button" className="btn-ghost hasher-remove-btn" onClick={reset}>
                  <TrashIcon /> {t("hasher.removeFile")}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
