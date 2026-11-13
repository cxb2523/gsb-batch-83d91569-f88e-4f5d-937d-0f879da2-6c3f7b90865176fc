export function createDebounced<T>(fn: (value: T) => void, waitMs: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (value: T) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(value), waitMs);
  };
}
