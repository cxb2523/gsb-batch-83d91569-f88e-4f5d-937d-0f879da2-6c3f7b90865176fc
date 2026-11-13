"use client";

import { useState } from "react";
import { Dialog, DialogContent, DialogTitle, DialogClose } from "@/components/ui/dialog";
import { useLocale } from "./useLocale";

const STORAGE_KEY = "ra-downloader-notice-seen";

export default function NoticeModal() {
  const { t } = useLocale();
  const [open, setOpen] = useState(() => typeof window !== "undefined" && !sessionStorage.getItem(STORAGE_KEY));

  function dismiss() {
    sessionStorage.setItem(STORAGE_KEY, "1");
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={(o: boolean) => !o && dismiss()}>
      <DialogContent className="modal-panel" showCloseButton={false}>
        <div className="modal-head">
          <DialogTitle>{t("notice.title")}</DialogTitle>
          <DialogClose className="modal-close" aria-label={t("common.close")}>
            &times;
          </DialogClose>
        </div>
        <div className="modal-body">
          <p style={{ margin: 0 }}>
            {t("notice.body1")}
            <a href="https://archive.org/" target="_blank" rel="noopener" style={{ color: "var(--link)" }}>
              archive.org
            </a>
            {t("notice.body2")}
            <a href="/faq" style={{ color: "var(--link)" }}>
              {t("footer.faqLegal")}
            </a>
            {t("notice.body3")}
          </p>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", padding: "0 18px 16px" }}>
          <button type="button" className="btn-primary" onClick={dismiss}>
            {t("notice.understood")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
