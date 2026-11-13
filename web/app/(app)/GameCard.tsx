"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useCart } from "./CartContext";
import { downloadGame } from "./download";
import { BoltIcon, CheckIcon, CopyIcon, PlusIcon, TrophyIcon } from "./icons";
import type { Game, Version, VersionsResponse } from "./types";
import { useLocale } from "./useLocale";

export default function GameCard({ game }: { game: Game }) {
  const { t } = useLocale();
  const cart = useCart();
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [imgLoaded, setImgLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const form = new FormData();
    form.append("game_id", game.id);
    fetch("/get_game_versions", { method: "POST", body: form })
      .then((res) => res.json() as Promise<VersionsResponse>)
      .then((data) => {
        if (!cancelled && data.success) setVersions(data.versions);
      });
    return () => {
      cancelled = true;
    };
  }, [game.id]);

  const active = versions?.[selectedIndex];
  const inCart = cart.has(game.id);

  function addToCart() {
    if (!active) return;
    cart.add({
      id: game.id,
      name: game.name,
      consoles: game.consoles,
      image_icon: game.image_icon,
      achievements: game.achievements,
      hash: active.hash,
      rom_path: active.rom_path,
    });
  }

  function copyHash() {
    if (!active) return;
    navigator.clipboard.writeText(active.hash).then(() => {
      toast(t("gamecard.hashCopied"));
    });
  }

  return (
    <div className="gcard">
      <div className="gcard-cover">
        {game.image_icon ? (
          <>
            {!imgLoaded && <div className="skeleton" style={{ position: "absolute", inset: 0 }} />}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={game.image_icon}
              alt=""
              loading="lazy"
              onLoad={() => setImgLoaded(true)}
              style={{ opacity: imgLoaded ? 1 : 0, transition: "opacity 200ms ease-out" }}
            />
          </>
        ) : (
          <div className="placeholder" />
        )}
        <span className="gcard-console">{game.consoles.join(", ") || "?"}</span>
        {game.achievements != null && (
          <a
            className="gcard-trophy"
            href={`https://retroachievements.org/game/${game.id}`}
            target="_blank"
            rel="noopener"
            title={t("gamecard.viewOnRa")}
          >
            <TrophyIcon /> {game.achievements}
          </a>
        )}
      </div>

      <div className="gcard-body">
        <div className="gcard-title">{game.name}</div>

        <div className="gcard-field">
          <label>{t("gamecard.versionRom")}</label>
          <select
            className="gcard-select"
            value={selectedIndex}
            disabled={!versions || versions.length === 0}
            onChange={(e) => setSelectedIndex(Number(e.target.value))}
          >
            {!versions && <option>{t("common.loading")}</option>}
            {versions?.length === 0 && <option>{t("gamecard.noVersions")}</option>}
            {versions?.map((v, idx) => (
              <option key={v.hash} value={idx}>
                {v.info?.filename || v.rom_path}
              </option>
            ))}
          </select>
        </div>

        <div className="gcard-field">
          <label>{t("gamecard.mirror")}</label>
          <div className="mirror-row">
            <span className="mirror-chip active">archive.org</span>
            <button type="button" className="mirror-chip" disabled title={t("common.soon")}>
              CoolROM
            </button>
          </div>
          <div className="mirror-note">
            {t("gamecard.otherMirrors")} <span className="soon-badge">{t("common.soon")}</span>
          </div>
        </div>

        <div className="gcard-actions">
          {active ? (
            <button type="button" className="btn-ghost" onClick={() => downloadGame(active.hash, game.name)}>
              <BoltIcon /> {t("common.download")}
            </button>
          ) : (
            <span className="btn-ghost" aria-disabled>
              <BoltIcon /> {t("common.download")}
            </span>
          )}
          <button type="button" className="icon-btn" onClick={copyHash} disabled={!active} title={t("gamecard.copyHash")}>
            <CopyIcon />
          </button>
          <button
            type="button"
            className={`icon-btn${inCart ? " in-cart" : ""}`}
            onClick={addToCart}
            disabled={!active || inCart}
            title={inCart ? t("common.inCart") : t("common.addToCart")}
          >
            {inCart ? <CheckIcon key="check" className="icon-pop" /> : <PlusIcon key="plus" />}
          </button>
        </div>
      </div>
    </div>
  );
}
