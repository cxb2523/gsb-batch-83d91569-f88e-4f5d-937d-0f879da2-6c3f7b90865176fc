import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { coverTint } from "../theme/coverTint";
import { Backdrop } from "./Backdrop";

// A detail page set inside its game's cover: the cover, heavily blurred, fills the background, and the
// palette's panels, borders and accent blend toward the cover's colour (see .cover-scene in styles.css).
// `coverSrc` must be same-origin (the cover cache or a local upload) for the colour to be read; a
// foreign image still shows as the backdrop, just without the tint.
export function CoverScene({ coverSrc, children }: { coverSrc?: string; children: ReactNode }) {
  const tint = useCoverTint(coverSrc);
  return (
    <div className={`cover-scene${tint ? " cover-scene--tinted" : ""}`} style={tint ? { "--tint": tint } as CSSProperties : undefined}>
      <Backdrop src={coverSrc} blur={40} />
      {children}
    </div>
  );
}

function useCoverTint(src?: string) {
  const [tint, setTint] = useState<string | null>(null);
  useEffect(() => {
    if (!src || typeof Image === "undefined") {
      setTint(null);
      return;
    }
    let current = true;
    const image = new Image();
    image.onload = () => { if (current) setTint(readTint(image)); };
    image.onerror = () => { if (current) setTint(null); };
    image.src = src;
    return () => {
      current = false;
      image.onload = null;
      image.onerror = null;
    };
  }, [src]);
  return tint;
}

// 32×32 is plenty for a main colour and keeps the read instant.
function readTint(image: HTMLImageElement) {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 32;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(image, 0, 0, 32, 32);
    return coverTint(context.getImageData(0, 0, 32, 32).data);
  } catch {
    // A cross-origin image taints the canvas; keep the plain palette.
    return null;
  }
}
