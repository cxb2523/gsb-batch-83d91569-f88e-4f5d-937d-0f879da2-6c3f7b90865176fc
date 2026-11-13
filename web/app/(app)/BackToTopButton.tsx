"use client";

import { useEffect, useState } from "react";
import { ArrowUpIcon } from "./icons";
import { useLocale } from "./useLocale";

const SHOW_AFTER_PX = 400;

export default function BackToTopButton() {
  const { t } = useLocale();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    function onScroll() {
      setVisible(window.scrollY > SHOW_AFTER_PX);
    }
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  if (!visible) return null;

  return (
    <button
      type="button"
      className="back-to-top"
      aria-label={t("common.backToTop")}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
    >
      <ArrowUpIcon />
    </button>
  );
}
