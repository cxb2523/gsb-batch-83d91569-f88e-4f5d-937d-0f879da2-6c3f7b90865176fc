import { TROPHY_GRID, TROPHY_PIXELS } from "./pixelTrophy";

export function SocialCard() {
  const cell = 108 / 14; // padding implicito: grilla de 8 ocupa ~60% de la caja de 108px
  const pad = (108 - TROPHY_GRID * cell) / 2;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#141414",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
        <div
          style={{
            display: "flex",
            position: "relative",
            width: 108,
            height: 108,
            borderRadius: 24,
            backgroundColor: "#cc9900",
          }}
        >
          {TROPHY_PIXELS.map(([x, y]) => (
            <div
              key={`${x}-${y}`}
              style={{
                display: "flex",
                position: "absolute",
                left: pad + x * cell,
                top: pad + y * cell,
                width: cell,
                height: cell,
                backgroundColor: "#141414",
              }}
            />
          ))}
        </div>
        <div style={{ display: "flex", fontSize: 72, fontWeight: 800, letterSpacing: -2, color: "#ededed" }}>
          RA Downloader
        </div>
      </div>
      <div
        style={{
          display: "flex",
          marginTop: 36,
          fontSize: 30,
          color: "#b4b4b4",
          maxWidth: 860,
          textAlign: "center",
        }}
      >
        Buscá y descargá ROMs compatibles con RetroAchievements
      </div>
      <div style={{ display: "flex", marginTop: 44, fontSize: 24, color: "#cc9900", fontWeight: 700 }}>
        8.460+ juegos indexados
      </div>
    </div>
  );
}
