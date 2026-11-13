"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { SearchIcon } from "./icons";
import type { ConsoleCount } from "./types";
import { useLocale } from "./useLocale";

export default function ConsoleFilterDropdown({
  consoles,
  label,
  value,
  selected,
  onChange,
}: {
  consoles: ConsoleCount[];
  /** Texto del boton cuando no hay ninguna consola de esta lista seleccionada (ej. el nombre de la compania). */
  label: string;
  /** true si el valor seleccionado actual pertenece a esta lista. */
  selected: boolean;
  value: string;
  onChange: (name: string) => void;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Posicion calculada a mano y el panel va en un portal a <body>: .pill-row
  // tiene overflow-x: auto, que en CSS tambien clippea verticalmente -- un
  // panel position:absolute anidado ahi adentro queda invisible/inclickeable
  // mas alla de la altura de la fila, sin importar su z-index.
  // El panel usa position:absolute (coordenadas de documento, no de viewport)
  // sumando window.scroll{X,Y} a getBoundingClientRect() -- con position:fixed
  // quedaba "pegado" a la pantalla al scrollear en vez de seguir al boton.
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function close() {
    setOpen(false);
    setQuery("");
  }

  function toggle() {
    if (!open && triggerRef.current) {
      const r = triggerRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6 + window.scrollY, left: r.left + window.scrollX });
    }
    setOpen((v) => !v);
  }

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (panelRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      close();
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const filtered = consoles.filter((c) => c.name.toLowerCase().includes(query.toLowerCase()));
  const selectedConsole = selected ? consoles.find((c) => c.name === value) : undefined;

  return (
    <>
      <button type="button" ref={triggerRef} className={`pill${selected ? " active" : ""}`} onClick={toggle}>
        {selectedConsole?.icon_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={selectedConsole.icon_url} alt="" className="pill-icon" />
        )}
        {selected ? value : label}
      </button>
      {open &&
        pos &&
        createPortal(
          <div className="console-dropdown" ref={panelRef} style={{ top: pos.top, left: pos.left }}>
            <div className="console-dropdown-search">
              <SearchIcon />
              <input
                ref={inputRef}
                type="text"
                placeholder={t("dropdown.searchConsole")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") close();
                }}
              />
            </div>
            <div className="console-dropdown-list">
              {filtered.length === 0 && <div className="console-dropdown-empty">{t("common.noResults")}</div>}
              {filtered.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  className={`console-dropdown-item${value === c.name ? " active" : ""}`}
                  onClick={() => {
                    onChange(c.name);
                    close();
                  }}
                >
                  <span className="console-dropdown-item-label">
                    {c.icon_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={c.icon_url} alt="" className="console-dropdown-icon" />
                    )}
                    {c.name}
                  </span>
                  <span className="console-dropdown-count">{c.count}</span>
                </button>
              ))}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
