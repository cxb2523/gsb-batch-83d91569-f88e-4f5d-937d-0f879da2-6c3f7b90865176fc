import { writable } from 'svelte/store';

export interface Toast { id: number; msg: string; }

let seq = 0;
export const toasts = writable<Toast[]>([]);

export function toast(msg: string) {
  const t: Toast = { id: ++seq, msg };
  toasts.update((a) => [...a, t]);
  setTimeout(() => toasts.update((a) => a.filter((x) => x.id !== t.id)), 2800);
}
