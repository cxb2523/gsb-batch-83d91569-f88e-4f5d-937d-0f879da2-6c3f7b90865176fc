// Covers and artwork come from IGDB's image server. When one can't load (offline, or a removed image), the
// image is marked so CSS hides it and its frame shows empty, instead of the browser's broken-image icon.
// Image load and error events don't bubble, so one capturing listener on the root covers every <img>.
export function installImageFallback(root: Pick<Node, "addEventListener">) {
  root.addEventListener("error", event => {
    if (event.target instanceof HTMLImageElement) event.target.setAttribute("data-image-failed", "");
  }, true);
  root.addEventListener("load", event => {
    if (event.target instanceof HTMLImageElement) event.target.removeAttribute("data-image-failed");
  }, true);
}
