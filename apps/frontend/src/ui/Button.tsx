import type { ButtonHTMLAttributes } from "react";

export function Button({ variant = "outline", small = false, danger = false, className = "", type = "button", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline";
  small?: boolean;
  danger?: boolean;
}) {
  return <button type={type} className={`btn btn--${variant}${small ? " btn--small" : ""}${danger ? " btn--danger" : ""} ${className}`.trim()} {...props} />;
}
