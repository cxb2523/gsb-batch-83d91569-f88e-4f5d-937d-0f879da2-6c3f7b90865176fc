"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { disconnectRaAccount, fetchWantToPlay, getRaProfile, getRaStatus } from "./wantToPlay";
import type { RaProfile } from "./types";

export interface RaAccount {
  username: string;
}

interface WtpCounts {
  total: number;
  requested: number;
}

interface RaAccountContextValue {
  account: RaAccount | null;
  profile: RaProfile | null;
  wtpCounts: WtpCounts | null;
  statusLoading: boolean;
  setConnected: (username: string) => void;
  setWtpCounts: (total: number, requested: number) => void;
  disconnect: () => void;
  modalOpen: boolean;
  openModal: () => void;
  closeModal: () => void;
}

const RaAccountContext = createContext<RaAccountContextValue | null>(null);

export function RaAccountProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<RaAccount | null>(null);
  const [profile, setProfile] = useState<RaProfile | null>(null);
  const [wtpCounts, setWtpCountsState] = useState<WtpCounts | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  // La API Key vive solo en una cookie HttpOnly del servidor (ver
  // /api/ra/connect) -- el browser nunca la tiene, así que al montar hay que
  // preguntarle al servidor si ya hay una sesión activa (en vez de leer algo
  // propio del cliente).
  useEffect(() => {
    getRaStatus()
      .then((data) => {
        if (data.connected && data.username) setAccount({ username: data.username });
      })
      .finally(() => setStatusLoading(false));
  }, []);

  // Trae el perfil y el conteo de want-to-play cada vez que hay una cuenta
  // conectada -- tanto recién conectada como al retomar una sesión existente
  // tras recargar la página, para que el modal siempre pueda mostrar "Mi
  // Want to Play" y el conteo, no solo la primera vez que se conecta.
  useEffect(() => {
    if (!account) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reacciona a que la cuenta (sistema externo) cambió, no a estado derivado de un render anterior
      setProfile(null);
      setWtpCountsState(null);
      return;
    }
    getRaProfile().then((data) => {
      if (data.success) setProfile(data);
    });
    fetchWantToPlay().then((data) => {
      if (data.success) setWtpCountsState({ total: data.total ?? data.items.length, requested: data.requested ?? data.items.length });
    });
  }, [account]);

  // Funciones estables (useCallback): las consume GamesView como dependencia
  // de su propio efecto -- si cambiaran de referencia en cada render de este
  // provider (por ejemplo cada vez que llega el perfil), ese efecto
  // reaccionaría de nuevo y refetchearía want_to_play en loop.
  const setConnected = useCallback((username: string) => {
    setAccount({ username });
  }, []);

  const setWtpCounts = useCallback((total: number, requested: number) => {
    setWtpCountsState({ total, requested });
  }, []);

  const disconnect = useCallback(() => {
    setAccount(null);
    setWtpCountsState(null);
    void disconnectRaAccount();
  }, []);

  const openModal = useCallback(() => setModalOpen(true), []);
  const closeModal = useCallback(() => setModalOpen(false), []);

  return (
    <RaAccountContext.Provider
      value={{
        account,
        profile,
        wtpCounts,
        statusLoading,
        setConnected,
        setWtpCounts,
        disconnect,
        modalOpen,
        openModal,
        closeModal,
      }}
    >
      {children}
    </RaAccountContext.Provider>
  );
}

export function useRaAccount() {
  const ctx = useContext(RaAccountContext);
  if (!ctx) throw new Error("useRaAccount debe usarse dentro de RaAccountProvider");
  return ctx;
}
