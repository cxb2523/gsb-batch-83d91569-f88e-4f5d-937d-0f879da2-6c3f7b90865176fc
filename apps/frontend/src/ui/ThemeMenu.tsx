import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { PALETTES, type Palette } from "../theme/palettes";

function Dots({ palette }: { palette: Palette }) {
  return <span className="theme-menu__dots" aria-hidden="true">{[palette.bg, palette.panel, palette.accent].map((colour, i) => <span style={{ backgroundColor: colour }} key={i} />)}</span>;
}

export function ThemeMenu({ palette, setPaletteId }: { palette: Palette; setPaletteId: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    rootRef.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus();
    return () => { document.removeEventListener("pointerdown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const choose = (id: string) => { setPaletteId(id); setOpen(false); triggerRef.current?.focus(); };
  const moveFocus = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const options = [...(rootRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])];
    const index = options.indexOf(document.activeElement as HTMLElement);
    options[(index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length]?.focus();
  };

  return <div className="theme-menu" ref={rootRef}>
    <button type="button" ref={triggerRef} className="theme-menu__trigger" aria-haspopup="menu" aria-expanded={open} aria-label={`Theme: ${palette.name}`} title="Theme" onClick={() => setOpen(value => !value)}>
      <Dots palette={palette} /><span className="theme-menu__name">{palette.name}</span><span className="theme-menu__caret" aria-hidden="true">▾</span>
    </button>
    {open && <div className="theme-menu__popover panel" role="menu" aria-label="Theme" onKeyDown={moveFocus}>
      {(["standard", "darker"] as const).map(group => <div className="theme-menu__group" key={group}>
        <p className="theme-menu__heading">{group === "standard" ? "Standard" : "Darker"}</p>
        {PALETTES.filter(p => p.group === group).map(p => <button type="button" role="menuitemradio" aria-checked={p.id === palette.id} className="theme-menu__option" key={p.id} onClick={() => choose(p.id)}>
          <Dots palette={p} /><span>{p.name}</span><span className="theme-menu__check" aria-hidden="true">{p.id === palette.id ? "◆" : ""}</span>
        </button>)}
      </div>)}
    </div>}
  </div>;
}
