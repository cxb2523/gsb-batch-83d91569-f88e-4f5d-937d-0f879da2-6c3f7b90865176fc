"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import BackToTopButton from "./BackToTopButton";
import { CartProvider, useCart } from "./CartContext";
import CartDrawer from "./CartDrawer";
import Footer from "./Footer";
import HasherModal from "./HasherModal";
import NoticeModal from "./NoticeModal";
import { RaAccountProvider, useRaAccount } from "./RaAccountContext";
import RaAccountModal from "./RaAccountModal";
import {
  CartIcon,
  FingerprintIcon,
  FranceFlagIcon,
  LogoMark,
  PortugalFlagIcon,
  SearchIcon,
  SpainFlagIcon,
  UsFlagIcon,
  UserIcon,
} from "./icons";
import { LANGUAGES, type Locale } from "./i18n";
import { useLocale } from "./useLocale";

const LANG_FLAGS: Record<Locale, (props: { size?: number }) => ReactNode> = {
  es: SpainFlagIcon,
  en: UsFlagIcon,
  pt: PortugalFlagIcon,
  fr: FranceFlagIcon,
};

function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isHome = pathname === "/";
  const { items } = useCart();
  const { account, profile, modalOpen: raOpen, openModal: openRaModal, closeModal: closeRaModal } = useRaAccount();
  const { locale, setLocale, t } = useLocale();
  const [q, setQ] = useState("");
  const [cartOpen, setCartOpen] = useState(false);
  const [hasherOpen, setHasherOpen] = useState(false);

  function onSearchSubmit(e: FormEvent) {
    e.preventDefault();
    const term = q.trim();
    router.push(term ? `/?q=${encodeURIComponent(term)}` : "/");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link href="/" className="brand">
            <div className="mark">
              <LogoMark size={16} />
            </div>
            <div className="name">RA Downloader</div>
          </Link>

          {!isHome && (
            <form className="search" onSubmit={onSearchSubmit}>
              <SearchIcon />
              <input
                type="text"
                placeholder={t("topbar.searchPlaceholder")}
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </form>
          )}

          <div className="header-actions">
            <Select value={locale} onValueChange={(v) => setLocale(v as Locale)}>
              <SelectTrigger className="icon-btn-labeled" aria-label={t("topbar.langLabel")}>
                <SelectValue>
                  {(value: Locale) => {
                    const lang = LANGUAGES.find((l) => l.code === value) ?? LANGUAGES[0];
                    const Flag = LANG_FLAGS[lang.code];
                    return (
                      <>
                        <Flag />
                        <span className="btn-label">{lang.label}</span>
                      </>
                    );
                  }}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {LANGUAGES.map((l) => {
                  const Flag = LANG_FLAGS[l.code];
                  return (
                    <SelectItem key={l.code} value={l.code}>
                      <Flag /> {l.label}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>

          <div className="action-bar">
            <button type="button" className="icon-btn-labeled" onClick={() => setHasherOpen(true)}>
              <FingerprintIcon /> <span className="btn-label">{t("topbar.verifyRom")}</span>
            </button>
            <button type="button" className="icon-btn-labeled" onClick={openRaModal}>
              {profile?.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="topbar-avatar" src={profile.avatar_url} alt="" />
              ) : (
                <UserIcon />
              )}
              <span className="btn-label">{account?.username ?? t("topbar.connectRa")}</span>
            </button>
            <button type="button" className="cart-trigger" onClick={() => setCartOpen(true)} aria-label={t("topbar.openCart")}>
              <CartIcon />
              <span className="btn-label">{t("topbar.openCart")}</span>
              {items.length > 0 && (
                <span key={items.length} className="count">
                  {items.length}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="app-main">{children}</main>
      <Footer />
      <BackToTopButton />
      <NoticeModal />
      <CartDrawer open={cartOpen} onClose={() => setCartOpen(false)} />
      <HasherModal open={hasherOpen} onClose={() => setHasherOpen(false)} />
      <RaAccountModal open={raOpen} onClose={closeRaModal} />
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <RaAccountProvider>
      <CartProvider>
        <Shell>{children}</Shell>
      </CartProvider>
    </RaAccountProvider>
  );
}
