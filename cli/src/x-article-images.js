export const X_ARTICLE_IMAGE_LIMIT = 25;
export const X_ARTICLE_IMAGE_PLACEHOLDER = "【超过25张图片上限，需人工替换】";

// Limit in document order, retaining a usable source address instead of a
// temporary asset-server URL. Keep the original input untouched.
export function limitXArticleImages(html, mediaAssets) {
  const escape = value => String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const decode = value => value.replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
  const basename = value => {
    try { return decodeURIComponent(value.split(/[?#]/)[0].split(/[/\\]/).pop()); }
    catch { return value.split(/[/\\]/).pop(); }
  };
  const kept = new Set();
  const overflow = [];
  let count = 0;
  const content = String(html || "").replace(/<img\b[^>]*>/gi, tag => {
    const match = tag.match(/\ssrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i);
    if (!match) return tag;
    const src = decode(match[1] ?? match[2] ?? match[3]);
    const asset = mediaAssets.find(item => [item.blobUrl, item.url, item.path].includes(src))
      || mediaAssets.find(item => basename(item.name || item.path || "") === basename(src));
    count++;
    if (count <= X_ARTICLE_IMAGE_LIMIT) {
      if (asset) kept.add(asset);
      return tag;
    }
    const address = asset?.path || asset?.originalPath || asset?.sourceUrl
      || ([asset?.url, src].find(value => value && !/^(blob:|data:|https?:\/\/(localhost|127\.0\.0\.1)(:|\/))/i.test(value)))
      || asset?.name || src;
    overflow.push({ position: count, address });
    return `<p>${X_ARTICLE_IMAGE_PLACEHOLDER} ${escape(address)}</p>`;
  });
  return { content, overflow, mediaAssets: overflow.length || mediaAssets.length > X_ARTICLE_IMAGE_LIMIT
    ? mediaAssets.filter(asset => kept.has(asset)) : mediaAssets };
}

export function prepareXArticleImages(input) {
  // Multi-platform jobs share data; their X-specific limit is applied by the
  // platform adapter so other targets retain their full article.
  if (input.type !== "article" || input.platforms.length !== 1 || input.platforms[0] !== "x") return input;
  const field = input.data.content ? "content" : "rawContent";
  const media = input.assets.filter(asset => (asset.role || "media") === "media");
  const result = limitXArticleImages(input.data[field], media);
  if (!result.overflow.length && result.mediaAssets === media) return input;
  const retained = new Set(result.mediaAssets);
  return {
    ...input,
    data: { ...input.data, [field]: result.content, xArticleImageOverflow: result.overflow },
    assets: input.assets.filter(asset => (asset.role || "media") !== "media" || retained.has(asset)),
  };
}
