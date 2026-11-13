"use client";

import { useCallback, useEffect, useState } from "react";
import { initLocale, setLocale as setLocaleGlobal, subscribe, t as translate, type Key, type Locale } from "./i18n";

export function useLocale() {
  const [locale, setLocaleState] = useState<Locale>(() => initLocale());

  useEffect(() => subscribe(setLocaleState), []);

  const t = useCallback((key: Key) => translate(key, locale), [locale]);

  return {
    locale,
    setLocale: setLocaleGlobal,
    t,
  };
}
