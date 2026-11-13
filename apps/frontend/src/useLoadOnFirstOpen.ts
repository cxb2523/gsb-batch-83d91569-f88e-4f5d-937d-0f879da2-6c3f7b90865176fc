import { useEffect, useRef } from "react";

// Runs `load` the first time `open` turns true, and never again: the data then stays for the session.
export function useLoadOnFirstOpen(open: boolean, load: () => void) {
  const loaded = useRef(false);
  useEffect(() => {
    if (!open || loaded.current) return;
    loaded.current = true;
    load();
  }, [open]);
}
