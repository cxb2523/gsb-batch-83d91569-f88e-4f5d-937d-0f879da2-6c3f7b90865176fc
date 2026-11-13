import type { HTMLAttributes, ReactNode } from "react";
import { CornerOrnament } from "./CornerOrnament";

type PanelTag = "section" | "div" | "aside";

export function FramedPanel({ as: Tag = "section", className = "", children, ...rest }: HTMLAttributes<HTMLElement> & { as?: PanelTag; children: ReactNode }) {
  return (
    <Tag className={`panel ${className}`.trim()} {...rest}>
      <span className="panel__corner panel__corner--tl" aria-hidden="true"><CornerOrnament /></span>
      <span className="panel__corner panel__corner--tr" aria-hidden="true"><CornerOrnament /></span>
      <span className="panel__corner panel__corner--bl" aria-hidden="true"><CornerOrnament /></span>
      <span className="panel__corner panel__corner--br" aria-hidden="true"><CornerOrnament /></span>
      <div className="panel__body">{children}</div>
    </Tag>
  );
}
