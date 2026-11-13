"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ConsoleFilterDropdown from "./ConsoleFilterDropdown";
import { COMPANY_ORDER, companyOf } from "./consoleCompanies";
import GameCard from "./GameCard";
import GameCardSkeleton from "./GameCardSkeleton";
import { useCart } from "./CartContext";
import { useRaAccount } from "./RaAccountContext";
import { downloadGame } from "./download";
import { BoltIcon, CheckIcon, HeartIcon, SearchIcon } from "./icons";
import type { ConsoleCount, Game, GamesResponse, SearchResult } from "./types";
import { lookupHash } from "./verifyHash";
import { fetchWantToPlay } from "./wantToPlay";
import { resultsCount } from "./i18n";
import { useLocale } from "./useLocale";

const PAGE_SIZES = [10, 20, 50, 100];
const HASH_RE = /^[0-9a-f]{8,}$/i;
const SKELETON_COUNT = 12;

function Pager({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (page: number) => void }) {
  return (
    <div className="pager">
      <button type="button" disabled={page <= 1} onClick={() => onChange(1)}>
        «
      </button>
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ‹
      </button>
      <span className="num">
        {page} / {totalPages}
      </span>
      <button type="button" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        ›
      </button>
      <button type="button" disabled={page >= totalPages} onClick={() => onChange(totalPages)}>
        »
      </button>
    </div>
  );
}

export default function GamesView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const cart = useCart();
  const { account, setWtpCounts } = useRaAccount();
  const { locale, t } = useLocale();

  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [consoleFilter, setConsoleFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Sincroniza con ?q= de la URL: en el primer montaje (deep link) y cuando
  // otro componente (el buscador del topbar) navega a /?q=... mientras
  // esta vista ya está montada -- el valor inicial de useState no reacciona
  // a esos cambios por sí solo.
  useEffect(() => {
    const next = searchParams.get("q") ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sincroniza con la URL (sistema externo), no estado derivado de un render anterior
    setInput(next);
    setQ(next);
    setPage(1);
  }, [searchParams]);

  const [items, setItems] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [consoles, setConsoles] = useState<ConsoleCount[]>([]);
  const [allTotal, setAllTotal] = useState(0);

  const [wtpActive, setWtpActive] = useState(false);
  const [wtpItems, setWtpItems] = useState<Game[]>([]);
  const [wtpLoading, setWtpLoading] = useState(false);
  const [wtpError, setWtpError] = useState("");

  const [verify, setVerify] = useState<SearchResult | null>(null);
  const [verifyHash, setVerifyHash] = useState("");
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyError, setVerifyError] = useState("");

  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isHash = HASH_RE.test(q);

  useEffect(() => {
    fetch("/api/games?page=1&page_size=1")
      .then((res) => res.json() as Promise<GamesResponse>)
      .then((data) => setAllTotal(data.total || 0));
  }, []);

  useEffect(() => {
    if (isHash || wtpActive) return;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (consoleFilter) params.set("console", consoleFilter);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));

    // eslint-disable-next-line react-hooks/set-state-in-effect -- marca el inicio del fetch que dispara este mismo efecto, no estado derivado de un render anterior
    setLoading(true);
    fetch(`/api/games?${params.toString()}`)
      .then((res) => res.json() as Promise<GamesResponse>)
      .then((data) => {
        setItems(data.items || []);
        setTotal(data.total || 0);
        setTotalPages(data.total_pages || 1);
        setConsoles(data.consoles || []);
      })
      .finally(() => setLoading(false));
  }, [q, consoleFilter, page, pageSize, isHash, wtpActive]);

  useEffect(() => {
    if (!wtpActive || !account) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marca el inicio del fetch que dispara este mismo efecto, no estado derivado de un render anterior
    setWtpLoading(true);
    setWtpError("");
    fetchWantToPlay()
      .then((data) => {
        if (data.success) {
          setWtpItems(data.items);
          setWtpCounts(data.total ?? data.items.length, data.requested ?? data.items.length);
        } else {
          setWtpError(data.message || t("wtp.fetchError"));
        }
      })
      .catch(() => setWtpError(t("wtp.fetchError")))
      .finally(() => setWtpLoading(false));
  }, [wtpActive, account, t, setWtpCounts]);

  useEffect(() => {
    // Si se desconecta la cuenta mientras el filtro está activo, el pill
    // desaparece del pill-row -- sin esto no habría forma de volver al
    // catálogo normal.
    if (!account && wtpActive) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reacciona a que la cuenta (sistema externo) se desconectó, no a un render anterior
      setWtpActive(false);
    }
  }, [account, wtpActive]);

  useEffect(() => {
    if (!isHash) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- limpia el resultado de verificación anterior al salir del modo hash (sincroniza con el cambio de q/isHash)
      setVerify(null);
      setVerifyError("");
      return;
    }
    setVerifyLoading(true);
    setVerify(null);
    setVerifyError("");
    setVerifyHash(q);

    lookupHash(q)
      .then((data) => {
        if (data.success) setVerify(data);
        else setVerifyError(data.message || t("common.hashNotFound"));
      })
      .catch(() => setVerifyError(t("common.hashVerifyFailed")))
      .finally(() => setVerifyLoading(false));
  }, [q, isHash, t]);

  function runSearch(value: string) {
    const trimmed = value.trim();
    setQ(trimmed);
    setPage(1);
    router.replace(trimmed ? `/?q=${encodeURIComponent(trimmed)}` : "/");
  }

  function onInputChange(value: string) {
    setInput(value);
    if (typingTimer.current) clearTimeout(typingTimer.current);
    typingTimer.current = setTimeout(() => runSearch(value), 300);
  }

  function addVerifyToCart() {
    if (!verify) return;
    cart.add({
      id: verifyHash,
      name: verify.name ?? verifyHash,
      consoles: verify.console ? [verify.console] : [],
      image_icon: null,
      achievements: null,
      hash: verifyHash,
      rom_path: "",
    });
  }

  function toggleWtp() {
    setWtpActive((prev) => !prev);
    setConsoleFilter("");
    setPage(1);
  }

  const consolesByCompany = COMPANY_ORDER.map((company) => ({
    company,
    consoles: consoles.filter((c) => companyOf(c.name) === company).sort((a, b) => b.count - a.count),
  })).filter((g) => g.consoles.length > 0);

  // Modo "Mi Want to Play": wtpItems ya vino completo del server en un solo
  // fetch (el acumulado no suele pasar de un par de cientos de juegos), así
  // que el filtro por nombre/consola y la paginación se hacen client-side en
  // vez de pegarle a /api/games de nuevo en cada tecla.
  const filteredWtpItems = wtpItems.filter((g) => {
    const matchesConsole = !consoleFilter || g.consoles.includes(consoleFilter);
    const matchesQuery = !q || g.name.toLowerCase().includes(q.toLowerCase());
    return matchesConsole && matchesQuery;
  });
  const wtpTotalPages = Math.max(1, Math.ceil(filteredWtpItems.length / pageSize));
  const pagedWtpItems = filteredWtpItems.slice((page - 1) * pageSize, page * pageSize);

  return (
    <>
      <div className="title-row">
        <div>
          <h1>{t("games.title")}</h1>
          <div className="sub">
            <b className="num">{allTotal}</b> {t("games.indexedSuffix")}
          </div>
        </div>
      </div>

      <div className="search" style={{ marginBottom: 24, maxWidth: 420 }}>
        <SearchIcon />
        <input type="text" placeholder={t("games.searchPlaceholder")} value={input} onChange={(e) => onInputChange(e.target.value)} />
      </div>

      {isHash ? (
        <>
          {verifyLoading && <p className="empty-hint">{t("common.verifyingHash")}</p>}
          {verifyError && <p className="empty-hint">{verifyError}</p>}
          {verify && (
            <div className="verify">
              <div className="icon" />
              <div className="meta">
                <div className="name">{verify.name ?? t("games.foundName")}</div>
                <div className="sub">{verify.console ?? t("common.unknownConsole")}</div>
                <div className="hash">{verifyHash}</div>
              </div>
              <div className="checks">
                <span className={`badge ${verify.ra_recognized ? "ok" : "warn"}`}>
                  {verify.ra_recognized ? t("games.raRecognized") : t("games.raNotRecognized")}
                </span>
                <span className={`badge ${verify.link_ok ? "ok" : "warn"}`}>
                  {verify.link_ok ? t("games.linkVerified") : t("games.linkNotVerified")}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button type="button" className="btn-ghost" onClick={() => downloadGame(verifyHash, verify.name)}>
                  <BoltIcon /> {t("common.download")}
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={cart.has(verifyHash)}
                  onClick={addVerifyToCart}
                >
                  {cart.has(verifyHash) ? (
                    <span key="added" className="icon-pop" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <CheckIcon /> {t("common.inCart")}
                    </span>
                  ) : (
                    t("common.addToCart")
                  )}
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="pill-row">
            <button
              type="button"
              className={`pill${!wtpActive && consoleFilter === "" ? " active" : ""}`}
              onClick={() => {
                setConsoleFilter("");
                setWtpActive(false);
                setPage(1);
              }}
            >
              {t("dropdown.all")}
            </button>
            {account && (
              <button type="button" className={`pill${wtpActive ? " active" : ""}`} onClick={toggleWtp}>
                <HeartIcon /> {t("wtp.pill")}
              </button>
            )}
            {consolesByCompany.map(({ company, consoles: companyConsoles }) => (
              <ConsoleFilterDropdown
                key={company}
                label={company}
                consoles={companyConsoles}
                value={consoleFilter}
                selected={!wtpActive && companyConsoles.some((c) => c.name === consoleFilter)}
                onChange={(name) => {
                  setConsoleFilter(name);
                  setWtpActive(false);
                  setPage(1);
                }}
              />
            ))}
          </div>

          <div className="grid-head">
            <span>{resultsCount(wtpActive ? filteredWtpItems.length : total, consoleFilter, locale)}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div className="page-size">
                <label htmlFor="page-size-select">{t("games.showLabel")}</label>
                <select
                  id="page-size-select"
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                >
                  {PAGE_SIZES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <Pager page={page} totalPages={wtpActive ? wtpTotalPages : totalPages} onChange={setPage} />
            </div>
          </div>

          {wtpActive ? (
            wtpLoading ? (
              <div className="games-grid">
                {Array.from({ length: Math.min(pageSize, SKELETON_COUNT) }).map((_, i) => (
                  <GameCardSkeleton key={i} />
                ))}
              </div>
            ) : wtpError ? (
              <p className="empty-hint">{wtpError}</p>
            ) : pagedWtpItems.length === 0 ? (
              <p className="empty-hint">{t("wtp.noResults")}</p>
            ) : (
              <>
                <div className="games-grid">
                  {pagedWtpItems.map((g) => (
                    <GameCard key={g.id} game={g} />
                  ))}
                </div>
                <div className="grid-foot">
                  <Pager page={page} totalPages={wtpTotalPages} onChange={setPage} />
                </div>
              </>
            )
          ) : loading ? (
            <div className="games-grid">
              {Array.from({ length: Math.min(pageSize, SKELETON_COUNT) }).map((_, i) => (
                <GameCardSkeleton key={i} />
              ))}
            </div>
          ) : items.length === 0 ? (
            <p className="empty-hint">{t("games.noResults")}</p>
          ) : (
            <>
              <div className="games-grid">
                {items.map((g) => (
                  <GameCard key={g.id} game={g} />
                ))}
              </div>
              <div className="grid-foot">
                <Pager page={page} totalPages={totalPages} onChange={setPage} />
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
