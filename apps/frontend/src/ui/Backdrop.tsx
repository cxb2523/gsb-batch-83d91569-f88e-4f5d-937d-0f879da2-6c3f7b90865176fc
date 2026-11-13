import { useEffect, useState } from "react";

// "art" fills the space beside the list panel with the image, over a blurred fill of itself behind the panel.
// blur 40 is the detail pages' cover backdrop: only the cover's colours and shapes remain.
export function Backdrop({ src, fillSrc, blur, fit = "cover" }: { src?: string; fillSrc?: string; blur: 0 | 18 | 40; fit?: "cover" | "art" }) {
  const [current, setCurrent] = useState(src);
  const [previous, setPrevious] = useState<string | undefined>();

  useEffect(() => {
    if (src === current) return;
    setPrevious(current);
    setCurrent(src);
    const timeout = window.setTimeout(() => setPrevious(undefined), 240);
    return () => window.clearTimeout(timeout);
  }, [src]);

  const art = fit === "art" && !blur;
  return (
    <div className={`backdrop${blur ? " backdrop--blur" : ""}${blur === 40 ? " backdrop--blur-heavy" : ""}${art ? " backdrop--art" : ""}`} aria-hidden="true">
      {art && current && <img key={`fill-${current}`} className="backdrop__fill" src={fillSrc ?? current} alt="" draggable={false} />}
      {previous && <img className="backdrop__img backdrop__img--previous" src={previous} alt="" draggable={false} />}
      {current && <img key={current} className="backdrop__img backdrop__img--current" src={current} alt="" draggable={false} />}
      <div className="backdrop__scrim" />
    </div>
  );
}
