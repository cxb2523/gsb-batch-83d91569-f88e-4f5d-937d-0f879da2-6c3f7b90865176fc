import type { ReactNode } from "react";

export function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <label className={`field ${className}`.trim()}><span className="field__label">{label}</span>{children}</label>;
}

export function SelectShell({ children }: { children: ReactNode }) {
  return <span className="field__select">{children}</span>;
}
