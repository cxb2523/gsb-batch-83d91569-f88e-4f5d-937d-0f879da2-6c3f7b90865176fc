"use client";

import { useState, type FormEvent } from "react";
import { Dialog, DialogContent, DialogTitle, DialogClose } from "@/components/ui/dialog";
import { wtpFoundCount } from "./i18n";
import { UserIcon } from "./icons";
import { useLocale } from "./useLocale";
import { useRaAccount } from "./RaAccountContext";
import { connectRaAccount } from "./wantToPlay";

export default function RaAccountModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, locale } = useLocale();
  const { account, profile, wtpCounts, setConnected, disconnect } = useRaAccount();
  const [apiKey, setApiKey] = useState("");
  const [username, setUsername] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const trimmedUsername = username.trim();
      const data = await connectRaAccount(apiKey.trim(), trimmedUsername);
      if (data.success) {
        // El contexto trae perfil y conteo de want-to-play solo (ver el
        // efecto en RaAccountContext que reacciona a que account cambió).
        setConnected(trimmedUsername);
        setApiKey("");
        setUsername("");
      } else {
        setError(data.message || t("ra.connectError"));
      }
    } catch {
      setError(t("ra.connectError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o: boolean) => {
        if (!o) {
          setError("");
          onClose();
        }
      }}
    >
      <DialogContent className="modal-panel" style={{ maxWidth: 420 }} showCloseButton={false}>
        <div className="modal-head">
          <DialogTitle>{t("ra.title")}</DialogTitle>
          <DialogClose className="modal-close" aria-label={t("common.close")}>
            &times;
          </DialogClose>
        </div>
        <div className="modal-body">
          {account ? (
            <div className="ra-profile">
              <div className="ra-profile-head">
                {profile?.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="ra-profile-avatar" src={profile.avatar_url} alt="" />
                ) : (
                  <div className="ra-account-avatar">
                    <UserIcon size={20} />
                  </div>
                )}
                <div>
                  <div className="ra-account-name">{account.username}</div>
                  {profile?.motto && <div className="ra-profile-motto">&ldquo;{profile.motto}&rdquo;</div>}
                </div>
              </div>

              {profile && (
                <div className="ra-profile-stats">
                  <div>
                    <span className="num">{profile.total_points ?? 0}</span>
                    <label>{t("ra.points")}</label>
                  </div>
                  <div>
                    <span className="num">{profile.total_true_points ?? 0}</span>
                    <label>{t("ra.truePoints")}</label>
                  </div>
                </div>
              )}

              {wtpCounts && (
                <p className="ra-account-hint">{wtpFoundCount(wtpCounts.total, wtpCounts.requested, locale)}</p>
              )}

              <div className="ra-profile-actions">
                <button type="button" className="btn-primary" onClick={onClose}>
                  {t("common.accept")}
                </button>
                <button type="button" className="btn-ghost" onClick={disconnect}>
                  {t("ra.disconnect")}
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <p style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>{t("ra.body")}</p>

              <div className="gcard-field">
                <label htmlFor="ra-api-key">{t("ra.apiKeyLabel")}</label>
                <input
                  id="ra-api-key"
                  className="gcard-select"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={t("ra.apiKeyPlaceholder")}
                  required
                />
              </div>

              <div className="gcard-field">
                <label htmlFor="ra-username">{t("ra.usernameLabel")}</label>
                <input
                  id="ra-username"
                  className="gcard-select"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={t("ra.usernamePlaceholder")}
                  required
                />
              </div>

              <p style={{ margin: 0, fontSize: 11, color: "var(--faint)" }}>
                {t("ra.getApiKeyHint")}
                <a
                  href="https://retroachievements.org/controlpanel.php"
                  target="_blank"
                  rel="noopener"
                  style={{ color: "var(--link)" }}
                >
                  {t("ra.getApiKeyLink")}
                </a>
              </p>

              {error && <p className="empty-hint">{error}</p>}

              <button type="submit" className="btn-primary" disabled={loading} style={{ alignSelf: "flex-start" }}>
                {loading ? t("ra.connecting") : t("ra.connect")}
              </button>
            </form>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
