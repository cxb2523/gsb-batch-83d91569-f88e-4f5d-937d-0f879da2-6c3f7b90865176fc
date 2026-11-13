export function WallpaperPanel({
  hasNativePicker,
  hasWallpaper,
  onChooseWallpaper,
  onClearWallpaper
}: {
  hasNativePicker: boolean;
  hasWallpaper: boolean;
  onChooseWallpaper: (file?: File | null) => void;
  onClearWallpaper: () => void;
}) {
  return (
    <div className="wallpaper-controls" aria-label="Wallpaper controls">
      {hasNativePicker
        ? <button type="button" className="wallpaper-upload" onClick={() => onChooseWallpaper(null)}>Choose wallpaper</button>
        : (
          <label className="wallpaper-upload">
            Choose wallpaper
            <input type="file" accept="image/png,image/jpeg,image/webp,image/bmp,image/gif" onChange={event => onChooseWallpaper(event.target.files?.[0] ?? null)} />
          </label>
        )}
      {hasWallpaper && <button type="button" className="secondary wallpaper-clear" onClick={onClearWallpaper}>Clear</button>}
    </div>
  );
}
