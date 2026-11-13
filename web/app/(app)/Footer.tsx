"use client";

import Link from "next/link";
import { GithubIcon } from "./icons";
import { useLocale } from "./useLocale";

const REPO_URL = "https://github.com/pipetboy2001/retroAchievements-Download-games";

export default function Footer() {
  const { t } = useLocale();
  return (
    <footer className="site-footer">
      <a href={REPO_URL} target="_blank" rel="noopener" className="footer-repo">
        <GithubIcon size={14} />
        <span>{t("footer.collaborate")}</span>
      </a>
      <p>
        {t("footer.developedBy")}{" "}
        <a href="https://github.com/pipetboy2001" target="_blank" rel="noopener">
          Pipetboy
        </a>
        <span className="sep">·</span>
        <Link href="/faq">{t("footer.faqLegal")}</Link>
      </p>
    </footer>
  );
}
