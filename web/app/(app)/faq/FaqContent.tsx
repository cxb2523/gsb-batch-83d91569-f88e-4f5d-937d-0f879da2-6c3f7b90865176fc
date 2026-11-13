"use client";

import Link from "next/link";
import { useLocale } from "../useLocale";

export default function FaqContent() {
  const { t } = useLocale();
  return (
    <div className="faq-page">
      <div className="title-row">
        <div>
          <h1>{t("faq.title")}</h1>
        </div>
      </div>

      <div className="faq-panel">
        <details className="faq-item" open>
          <summary>{t("faq.q1")}</summary>
          <p className="faq-answer">{t("faq.a1")}</p>
        </details>

        <details className="faq-item" open>
          <summary>{t("faq.q2")}</summary>
          <p className="faq-answer">
            {t("faq.a2a")}
            <a href="https://archive.org/" target="_blank" rel="noopener" style={{ color: "var(--link)" }}>
              archive.org
            </a>
            {t("faq.a2b")}
          </p>
        </details>

        <details className="faq-item">
          <summary>{t("faq.q3")}</summary>
          <p className="faq-answer">
            {t("faq.a3a")}
            <strong>{t("faq.a3b")}</strong>
            {t("faq.a3c")}
          </p>
        </details>

        <details className="faq-item">
          <summary>{t("faq.q4")}</summary>
          <p className="faq-answer">{t("faq.a4")}</p>
        </details>

        <details className="faq-item">
          <summary>{t("faq.q5")}</summary>
          <p className="faq-answer">{t("faq.a5")}</p>
        </details>

        <h2>{t("faq.legalTitle")}</h2>
        <ul className="faq-list">
          <li>{t("faq.legal1")}</li>
          <li>{t("faq.legal2")}</li>
          <li>
            {t("faq.legal3a")}
            <strong>{t("faq.legal3b")}</strong>
            {t("faq.legal3c")}
          </li>
          <li>{t("faq.legal4")}</li>
          <li>{t("faq.legal5")}</li>
        </ul>

        <h2>{t("faq.tipsTitle")}</h2>
        <ul className="faq-list">
          <li>{t("faq.tip1")}</li>
          <li>{t("faq.tip2")}</li>
          <li>{t("faq.tip3")}</li>
        </ul>

        <div style={{ marginTop: 24 }}>
          <Link href="/" className="btn-primary">
            {t("common.backHome")}
          </Link>
        </div>
      </div>
    </div>
  );
}
