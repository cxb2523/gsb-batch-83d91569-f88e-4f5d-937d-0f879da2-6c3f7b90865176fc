import { useEffect, useRef, type RefObject } from "react";
import type { YearInReviewSummary } from "../../../../../shared/types";
import { igdbCoverSrc, screenshotSrc } from "../../artwork";
import { prefersReducedMotion } from "../../motion";

// The illustrated backdrop behind each chapter: a sea chart, a grimoire, a forge, an astrolabe, and the
// GOTY's own art. All five stay mounted and crossfade on the stage's data-realm. Drawn in SVG, so nothing
// ships as an image file, and the drawings read the year (ports per month, genres on the ring, the busiest month).

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function RealmScenes({ summary, scenes }: { summary: YearInReviewSummary; scenes: RefObject<HTMLDivElement | null> }) {
  const backdrop = summary.goty?.backdrop;
  const gotySrc = backdrop ? (backdrop.kind === "screenshot" ? screenshotSrc(backdrop.imageId, "hero") : igdbCoverSrc(backdrop.imageId, "detail")) : null;
  const busiest = summary.overview.busiestMonth ? summary.overview.busiestMonth.month - 1 : null;
  return (
    <div className="yir-scenes" ref={scenes} aria-hidden="true">
      <div className="yir-scene yir-scene--overview"><AtlasScene months={summary.overview.months} /></div>
      <div className="yir-scene yir-scene--taste"><GrimoireScene genres={summary.taste.genres.map(genre => genre.name)} /></div>
      <div className="yir-scene yir-scene--ratings"><ForgeScene /></div>
      <div className="yir-scene yir-scene--timing"><AstrolabeScene months={summary.overview.months} busiest={busiest} /></div>
      <div className="yir-scene yir-scene--goty">
        {gotySrc ? <img className="yir-scene__art" src={gotySrc} alt="" draggable={false} /> : <div className="yir-scene__art yir-scene__art--none" />}
      </div>
    </div>
  );
}

// A smooth path through the points (Catmull-Rom as cubic Béziers).
function routeThrough(points: Array<[number, number]>) {
  let path = `M${points[0][0]} ${points[0][1]}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const [x0, y0] = points[index - 1] ?? points[index];
    const [x1, y1] = points[index];
    const [x2, y2] = points[index + 1];
    const [x3, y3] = points[index + 2] ?? points[index + 1];
    path += ` C${(x1 + (x2 - x0) / 6).toFixed(1)} ${(y1 + (y2 - y0) / 6).toFixed(1)} ${(x2 - (x3 - x1) / 6).toFixed(1)} ${(y2 - (y3 - y1) / 6).toFixed(1)} ${x2} ${y2}`;
  }
  return path;
}

// One port per month along the voyage, January first.
const PORTS: Array<[number, number]> = [[840, 330], [930, 290], [1010, 340], [1000, 450], [1090, 480], [1180, 400], [1260, 320], [1330, 420], [1250, 520], [1210, 620], [1320, 650], [1420, 600]];
const ROUTE = routeThrough(PORTS);
const MOUNTAINS = [[850, 330], [880, 322], [910, 336], [940, 318], [1300, 610], [1330, 600], [1360, 614], [960, 420], [990, 430]];
const TREES = [[820, 420], [836, 432], [852, 418], [1220, 660], [1236, 672], [1252, 658], [1268, 670], [1400, 690], [1416, 700]];
const CONTINENTS = [
  "M790 300 C850 240 970 250 1020 300 S1110 380 1070 450 S990 560 910 540 S790 470 810 400 Z",
  "M1180 560 C1260 500 1400 520 1440 590 S1430 720 1340 740 S1190 720 1170 660 Z"
];

function AtlasScene({ months }: { months: number[] }) {
  return (
    <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMaxYMid slice">
      <defs>
        <radialGradient id="yir-a-parch" cx="45%" cy="40%" r="75%"><stop offset="0" stopColor="#efdcae" /><stop offset=".6" stopColor="#c9a466" /><stop offset="1" stopColor="#6e4a22" /></radialGradient>
        <linearGradient id="yir-a-roll" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#6b4a26" /><stop offset=".45" stopColor="#e6cc96" /><stop offset="1" stopColor="#4a2f14" /></linearGradient>
        <linearGradient id="yir-a-brass" x1="0" x2="1"><stop offset="0" stopColor="#6e4b1c" /><stop offset=".5" stopColor="#f3dca0" /><stop offset="1" stopColor="#8a6428" /></linearGradient>
        <radialGradient id="yir-a-candle"><stop offset="0" stopColor="#ffd58a" stopOpacity=".55" /><stop offset="1" stopColor="#ffd58a" stopOpacity="0" /></radialGradient>
        <filter id="yir-a-rough"><feTurbulence type="fractalNoise" baseFrequency=".012" numOctaves={3} seed={7} result="n" /><feDisplacementMap in="SourceGraphic" in2="n" scale={28} /></filter>
        <filter id="yir-a-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".75" numOctaves={2} seed={3} /><feColorMatrix values="0 0 0 0 .35  0 0 0 0 .22  0 0 0 0 .08  0 0 0 .5 0" /><feComposite in2="SourceGraphic" operator="in" /></filter>
        <filter id="yir-a-shadow"><feGaussianBlur stdDeviation="18" /></filter>
      </defs>
      <rect width="1600" height="1000" fill="#0a0f22" />
      <g transform="rotate(-7 1150 520)">
        <rect x="720" y="170" width="900" height="720" fill="#000" opacity=".6" filter="url(#yir-a-shadow)" />
        <g filter="url(#yir-a-rough)"><rect x="700" y="150" width="900" height="720" fill="url(#yir-a-parch)" /></g>
        <rect x="712" y="162" width="876" height="696" filter="url(#yir-a-grain)" fill="#fff" />
        <circle cx="1480" cy="760" r="70" fill="#7a4a1c" opacity=".12" />
        <circle cx="840" cy="250" r="40" fill="#7a4a1c" opacity=".1" />
        <rect x="740" y="190" width="820" height="640" fill="none" stroke="#5a3a1c" strokeWidth="2" />
        <rect x="750" y="200" width="800" height="620" fill="none" stroke="#5a3a1c" strokeDasharray="2 6" />
        <g fill="rgba(110,70,30,.22)" stroke="#4a2d14" strokeWidth="2.5">
          {CONTINENTS.map(path => <path key={path} d={path} />)}
          <path d="M1200 280 C1240 260 1290 270 1300 300 S1260 350 1220 340 S1180 300 1200 280 Z" />
          <path d="M880 680 c20 -14 50 -10 56 6 s-20 30 -44 26 s-26 -20 -12 -32z" />
        </g>
        <g fill="none" stroke="#4a2d14" strokeWidth="10" opacity=".1">{CONTINENTS.map(path => <path key={path} d={path} />)}</g>
        <g fill="none" stroke="#4a2d14" strokeWidth="2">{MOUNTAINS.map(([x, y]) => <path key={`${x},${y}`} d={`M${x} ${y} l14 -28 l14 28 M${x + 14} ${y - 28} l-4 12`} />)}</g>
        <g fill="#5a3a1c" stroke="#4a2d14" strokeWidth="2">{TREES.map(([x, y]) => <g key={`${x},${y}`}><circle cx={x} cy={y - 8} r="6" /><path d={`M${x} ${y - 2} v8`} /></g>)}</g>
        <path d="M1040 700 q20 -30 40 0 q20 -30 40 0 q20 -30 40 0" fill="none" stroke="#3a4a4a" strokeWidth="5" strokeLinecap="round" />
        <circle cx="1034" cy="696" r="8" fill="#3a4a4a" />
        <path className="yir-march" d={ROUTE} fill="none" stroke="#8a1f1f" strokeWidth="3.5" strokeDasharray="10 8" strokeLinecap="round" />
        {PORTS.map(([x, y], month) => {
          const count = months[month] ?? 0;
          const radius = count ? 7 + Math.min(count, 8) * 3 : 4;
          return (
            <g key={month}>
              <circle cx={x} cy={y} r={radius} fill={count ? "#8a1f1f" : "#c9a466"} stroke="#3a2410" strokeWidth="2" />
              <text x={x} y={y - radius - 7} textAnchor="middle" fontFamily="'IM Fell English SC', serif" fontSize="17" fill="#3a2410">{MONTHS[month]}</text>
            </g>
          );
        })}
        <g transform="translate(1470 300)">
          <circle r="92" fill="none" stroke="#4a2d14" strokeWidth="2" />
          <circle r="84" fill="none" stroke="#4a2d14" strokeDasharray="3 5" />
          <g className="yir-spin yir-spin--reverse">
            {Array.from({ length: 8 }, (_, point) => (
              <path key={point} d={`M0 0 L-9 -12 L0 -${point % 2 ? 44 : 78} L9 -12 Z`} transform={`rotate(${point * 45})`} fill={point % 2 ? "#6b4a26" : point === 0 ? "#8a1f1f" : "#3a2410"} />
            ))}
          </g>
          <circle r="7" fill="#e8c26a" stroke="#3a2410" strokeWidth="2" />
          <text y="-100" textAnchor="middle" fontFamily="'IM Fell English SC', serif" fontSize="26" fill="#3a2410">N</text>
        </g>
        <g transform="translate(780 770)">
          <path d="M0 0 h300 l-18 24 l18 24 h-300 l18 -24 z" fill="#e8d2a0" stroke="#5a3a1c" strokeWidth="2" />
          <text x="150" y="31" textAnchor="middle" fontFamily="'IM Fell English SC', serif" fontSize="20" fill="#3a2410">Terra Ludorum</text>
        </g>
        <rect x="684" y="126" width="932" height="40" rx="20" fill="url(#yir-a-roll)" />
        <rect x="684" y="856" width="932" height="40" rx="20" fill="url(#yir-a-roll)" />
      </g>
      <g transform="rotate(22 900 900)">
        <path d="M900 640 L884 960 L894 962 Z" fill="url(#yir-a-brass)" />
        <path d="M900 640 L950 950 L960 946 Z" fill="url(#yir-a-brass)" />
        <circle cx="900" cy="640" r="12" fill="url(#yir-a-brass)" stroke="#4a3010" strokeWidth="2" />
      </g>
      <ellipse className="yir-pulse" cx="1540" cy="180" rx="300" ry="240" fill="url(#yir-a-candle)" />
      <g transform="translate(1540 190)">
        <rect x="-18" y="0" width="36" height="120" fill="#efe3c4" />
        <path d="M-18 0 q18 10 36 0" fill="#d8c8a0" />
        <path className="yir-flame" d="M0 -46 C12 -26 12 -8 0 0 C-12 -8 -12 -26 0 -46Z" fill="#ffd27a" />
      </g>
    </svg>
  );
}

// Books on a shelf, drawn once with a fixed seed so they never shuffle between renders.
const SHELF_BOOKS = (() => {
  let seed = 5;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const books: Array<{ x: number; y: number; width: number; height: number; fill: string; lean: boolean }> = [];
  for (let shelf = 130; shelf < 1000; shelf += 150) {
    let x = 868;
    while (x < 990) {
      const width = 12 + random() * 16;
      const height = 80 + random() * 44;
      const hue = [140, 30, 0, 200, 50][Math.floor(random() * 5)];
      books.push({ x, y: shelf - height, width, height, fill: `hsl(${hue} 35% ${Math.round(14 + random() * 14)}%)`, lean: random() > 0.9 });
      x += width + 2;
    }
  }
  return books;
})();
const RUNE_LINES = Array.from({ length: 7 }, (_, line) => 720 + line * 14);
const FLOATING_PAGES = Array.from({ length: 5 }, (_, page) => ({ x: 1000 + page * 110, y: 230 + (page % 3) * 120, angle: -20 + page * 11 }));

function GrimoireScene({ genres }: { genres: string[] }) {
  const words = (genres.length ? genres.slice(0, 7) : ["Grimoire of play"]).join(" ✦ ").toUpperCase();
  return (
    <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMaxYMid slice">
      <defs>
        <linearGradient id="yir-g-page" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#f1ecd0" /><stop offset="1" stopColor="#b8b286" /></linearGradient>
        <linearGradient id="yir-g-leather" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#2f5a40" /><stop offset="1" stopColor="#0d1f16" /></linearGradient>
        <linearGradient id="yir-g-beam" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stopColor="#b6ffcf" stopOpacity=".7" /><stop offset="1" stopColor="#b6ffcf" stopOpacity="0" /></linearGradient>
        <radialGradient id="yir-g-moon" cx="50%" cy="40%" r="60%"><stop offset="0" stopColor="#bfe8d8" /><stop offset="1" stopColor="#1c4a3c" /></radialGradient>
        <linearGradient id="yir-g-wood" x1="0" x2="1"><stop offset="0" stopColor="#2a170a" /><stop offset=".5" stopColor="#5a3518" /><stop offset="1" stopColor="#2a170a" /></linearGradient>
        <filter id="yir-g-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        <path id="yir-g-ring" d="M1240 380 m-128 0 a128 128 0 1 1 256 0 a128 128 0 1 1 -256 0" />
      </defs>
      <rect width="1600" height="1000" fill="#06150f" />
      <path d="M1360 520 L1360 200 Q1360 60 1460 30 Q1560 60 1560 200 L1560 520 Z" fill="url(#yir-g-moon)" opacity=".75" />
      <circle cx="1470" cy="170" r="46" fill="#effbf4" opacity=".9" />
      <path d="M1460 30 V520 M1360 300 H1560" stroke="#06150f" strokeWidth="12" />
      <path d="M1360 520 L1360 200 Q1360 60 1460 30 Q1560 60 1560 200 L1560 520 Z" fill="none" stroke="#1c2e25" strokeWidth="18" />
      <rect x="860" y="0" width="150" height="1000" fill="#0b1a13" />
      {[130, 280, 430, 580, 730, 880].map(y => <rect key={y} x="860" y={y} width="150" height="14" fill="#2a1a0e" />)}
      {SHELF_BOOKS.map(book => (
        <g key={`${book.x},${book.y}`} transform={book.lean ? `rotate(-8 ${book.x} ${book.y + book.height})` : undefined}>
          <rect x={book.x} y={book.y} width={book.width} height={book.height} fill={book.fill} />
          <rect x={book.x} y={book.y + 14} width={book.width} height="3" fill="#b89a4a" opacity=".6" />
        </g>
      ))}
      <polygon className="yir-pulse" points="1060,700 1420,700 1580,90 900,90" fill="url(#yir-g-beam)" opacity=".55" />
      <g filter="url(#yir-g-glow)" stroke="#9be3a8" fill="none" strokeWidth="2.2">
        <g className="yir-spin">
          <circle cx="1240" cy="380" r="160" />
          <circle cx="1240" cy="380" r="146" strokeDasharray="4 8" />
          <text fontFamily="'Uncial Antiqua', serif" fontSize="17" letterSpacing="3" fill="#b6ffcf" stroke="none"><textPath href="#yir-g-ring">{`${words} ✦ ${words} ✦`}</textPath></text>
        </g>
        <g className="yir-spin yir-spin--reverse">
          <circle cx="1240" cy="380" r="100" />
          <polygon points="1240,280 1326.6,430 1153.4,430" />
          <polygon points="1240,480 1153.4,330 1326.6,330" />
          <circle cx="1240" cy="380" r="26" />
        </g>
      </g>
      {FLOATING_PAGES.map(page => (
        <g key={page.x} transform={`rotate(${page.angle} ${page.x + 17} ${page.y + 22})`}>
          <rect className="yir-drift" x={page.x} y={page.y} width="34" height="44" fill="#e8e3c4" opacity=".7" />
        </g>
      ))}
      <polygon points="990,850 1490,850 1470,880 1010,880" fill="url(#yir-g-wood)" />
      <polygon points="1170,880 1310,880 1290,1000 1190,1000" fill="url(#yir-g-wood)" />
      <path d="M1010 700 C1100 655 1180 668 1240 692 C1300 668 1380 655 1470 700 L1470 852 C1380 818 1300 822 1240 856 C1180 822 1100 818 1010 852 Z" fill="url(#yir-g-leather)" stroke="#b89a4a" strokeWidth="2" />
      <path d="M1240 702 C1180 672 1110 672 1030 690 L1030 832 C1110 814 1180 814 1240 842 Z" fill="url(#yir-g-page)" />
      <path d="M1240 702 C1300 672 1370 672 1450 690 L1450 832 C1370 814 1300 814 1240 842 Z" fill="url(#yir-g-page)" />
      <path d="M1240 702 V842" stroke="#6e6a48" strokeWidth="2" />
      <g stroke="#2f5a40" strokeWidth="2.4" fill="none" opacity=".6">
        {RUNE_LINES.map(y => <path key={y} d={`M1056 ${y} Q1136 ${y - 10} 1216 ${y + 4}`} strokeDasharray="18 4 8 4 26 4 10 4" />)}
      </g>
      <g transform="translate(1345 760)" filter="url(#yir-g-glow)" fill="none" stroke="#2fae6a" strokeWidth="2.5">
        <circle r="38" /><polygon points="0,-38 33,19 -33,19" /><circle r="8" fill="#2fae6a" />
      </g>
      {[1020, 1460].map(x => (
        <g key={x} transform={`translate(${x} 790)`}>
          <ellipse className="yir-pulse" rx="70" ry="70" cy="-60" fill="#ffe29a" opacity=".12" />
          <rect x="-10" y="0" width="20" height="60" fill="#e6dfc2" />
          <path className="yir-flame" d="M0 -30 C9 -16 9 -5 0 0 C-9 -5 -9 -16 0 -30Z" fill="#c9ffb0" />
        </g>
      ))}
    </svg>
  );
}

const FLAMES: Array<[number, number]> = [[1150, 1], [1200, 1.3], [1250, 1.6], [1300, 1.25], [1350, 0.95], [1225, 1.1], [1280, 1.05]];

function ForgeScene() {
  return (
    <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMaxYMid slice">
      <defs>
        <pattern id="yir-f-bricks" width="120" height="60" patternUnits="userSpaceOnUse">
          <rect width="120" height="60" fill="#1c0d09" />
          <rect x="2" y="2" width="116" height="26" fill="#2b140e" />
          <rect x="-58" y="32" width="116" height="26" fill="#26120c" />
          <rect x="62" y="32" width="116" height="26" fill="#2e1610" />
        </pattern>
        <radialGradient id="yir-f-fire" cx="50%" cy="80%" r="60%"><stop offset="0" stopColor="#fff3b0" /><stop offset=".3" stopColor="#ffb347" /><stop offset=".65" stopColor="#d6461c" /><stop offset="1" stopColor="#3a0c05" stopOpacity="0" /></radialGradient>
        <linearGradient id="yir-f-flame" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stopColor="#fff2b0" /><stop offset=".45" stopColor="#ff9a3a" /><stop offset="1" stopColor="#c2301a" stopOpacity="0" /></linearGradient>
        <radialGradient id="yir-f-spill"><stop offset="0" stopColor="#ff8a3d" stopOpacity=".55" /><stop offset="1" stopColor="#ff8a3d" stopOpacity="0" /></radialGradient>
        <linearGradient id="yir-f-iron" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4a4448" /><stop offset=".25" stopColor="#26232a" /><stop offset="1" stopColor="#0e0c10" /></linearGradient>
        <linearGradient id="yir-f-hot" x1="0" x2="1"><stop offset="0" stopColor="#c2361a" /><stop offset=".55" stopColor="#ffb347" /><stop offset="1" stopColor="#fff6c8" /></linearGradient>
        <radialGradient id="yir-f-vignette" cx="72%" cy="55%" r="75%"><stop offset=".3" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity=".85" /></radialGradient>
        <filter id="yir-f-glow" x="-30%" y="-300%" width="160%" height="700%"><feGaussianBlur stdDeviation="7" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <rect width="1600" height="1000" fill="url(#yir-f-bricks)" />
      <rect y="760" width="1600" height="240" fill="#150907" />
      <polygon points="1030,190 1470,190 1370,30 1130,30" fill="#140b09" stroke="#2c1a14" strokeWidth="4" />
      <rect x="1190" y="-10" width="120" height="45" fill="#140b09" />
      <path d="M1040 640 L1040 360 A210 210 0 0 1 1460 360 L1460 640 Z" fill="#0a0403" />
      <ellipse className="yir-pulse" cx="1250" cy="560" rx="200" ry="140" fill="url(#yir-f-fire)" />
      <g>
        {FLAMES.map(([x, size], index) => (
          <path key={index} className="yir-flame" d={`M${x - 40} 640 C${x - 50} ${640 - 90 * size} ${x - 10} ${640 - 120 * size} ${x} ${640 - 190 * size} C${x + 20} ${640 - 120 * size} ${x + 50} ${640 - 80 * size} ${x + 40} 640 Z`} fill="url(#yir-f-flame)" opacity=".9" />
        ))}
      </g>
      <path d="M1040 640 L1040 360 A210 210 0 0 1 1460 360 L1460 640" fill="none" stroke="#3a2216" strokeWidth="44" strokeDasharray="52 6" />
      <rect x="990" y="630" width="520" height="40" fill="#2c1a14" />
      <rect x="990" y="630" width="520" height="4" fill="#ff8a3d" opacity=".5" />
      <ellipse cx="1250" cy="800" rx="480" ry="110" fill="url(#yir-f-spill)" />
      {[960, 1540].map(x => (
        <g key={x}>
          <path d={`M${x} 0 V300`} stroke="#2a2220" strokeWidth="10" strokeDasharray="18 6" strokeLinecap="round" />
          <path d={`M${x} 300 v30 m-16 0 a16 16 0 1 0 32 0`} fill="none" stroke="#2a2220" strokeWidth="7" />
        </g>
      ))}
      <rect x="860" y="820" width="130" height="150" rx="10" fill="#3a2414" />
      <rect x="856" y="846" width="138" height="10" fill="#1a1210" />
      <rect x="856" y="930" width="138" height="10" fill="#1a1210" />
      <ellipse cx="925" cy="820" rx="65" ry="14" fill="#10262a" />
      <g fill="none" stroke="#c8c0b8" strokeWidth="10" strokeLinecap="round" opacity=".5">
        <path className="yir-steam" d="M905 810 q-14 -30 4 -60" />
        <path className="yir-steam" d="M930 810 q14 -30 -4 -60" />
        <path className="yir-steam" d="M950 810 q-10 -26 6 -54" />
      </g>
      <path d="M1000 715 L1400 715 C1450 715 1500 705 1540 690 C1510 740 1460 770 1400 772 L1330 772 C1320 800 1320 830 1350 850 L1390 870 L1400 905 L1050 905 L1060 870 L1100 850 C1130 830 1130 800 1120 772 L1040 772 C1015 772 1000 750 1000 715 Z" fill="url(#yir-f-iron)" />
      <path d="M1000 715 L1400 715 C1450 715 1500 705 1540 690" fill="none" stroke="#ff9a4a" strokeWidth="3" opacity=".75" />
      <g filter="url(#yir-f-glow)"><polygon points="1030,705 1370,697 1398,702 1370,708 1030,712" fill="url(#yir-f-hot)" /></g>
      <rect x="1012" y="690" width="14" height="34" fill="#1a1412" />
      <rect x="960" y="704" width="52" height="8" fill="#3a2414" />
      <circle cx="955" cy="708" r="8" fill="#1a1412" />
      <g transform="rotate(-16 1470 900)">
        <rect x="1462" y="740" width="14" height="175" fill="#5a3a22" />
        <rect x="1430" y="722" width="82" height="38" fill="url(#yir-f-iron)" />
        <rect x="1430" y="722" width="82" height="3" fill="#ff9a4a" opacity=".6" />
      </g>
      <rect width="1600" height="1000" fill="url(#yir-f-vignette)" />
    </svg>
  );
}

const DIAL = { x: 1200, y: 520 };
const monthAngle = (month: number) => month * 30 + 15 - 90;
const onDial = (degrees: number, radius: number) => {
  const radians = (degrees * Math.PI) / 180;
  return { x: DIAL.x + radius * Math.cos(radians), y: DIAL.y + radius * Math.sin(radians) };
};
const STARS: Array<[number, number]> = [[160, 120], [260, 200], [420, 90], [560, 160], [700, 80], [380, 300], [120, 380], [620, 420], [820, 140], [980, 60]];

function AstrolabeScene({ months, busiest }: { months: number[]; busiest: number | null }) {
  const { x: cx, y: cy } = DIAL;
  return (
    <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMaxYMid slice">
      <defs>
        <radialGradient id="yir-t-sky" cx="70%" cy="40%" r="80%"><stop offset="0" stopColor="#34205e" /><stop offset="1" stopColor="#0b0719" /></radialGradient>
        <radialGradient id="yir-t-brass" cx="40%" cy="35%" r="75%"><stop offset="0" stopColor="#f8e3a8" /><stop offset=".5" stopColor="#c0913e" /><stop offset="1" stopColor="#5e3e14" /></radialGradient>
        <radialGradient id="yir-t-plate" cx="45%" cy="40%" r="70%"><stop offset="0" stopColor="#2e2150" /><stop offset="1" stopColor="#140c2a" /></radialGradient>
        <linearGradient id="yir-t-rule" x1="0" x2="1"><stop offset="0" stopColor="#8a6428" /><stop offset=".5" stopColor="#f6e2a6" /><stop offset="1" stopColor="#8a6428" /></linearGradient>
        <mask id="yir-t-moon"><circle cx="1500" cy="130" r="64" fill="#fff" /><circle cx="1526" cy="112" r="58" fill="#000" /></mask>
        <filter id="yir-t-glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        <filter id="yir-t-shadow"><feGaussianBlur stdDeviation="22" /></filter>
      </defs>
      <rect width="1600" height="1000" fill="url(#yir-t-sky)" />
      <g stroke="#9d7dff" strokeWidth="1.2" fill="none" opacity=".35">
        <polyline points="160,120 260,200 420,90 560,160 700,80" />
        <polyline points="380,300 260,200" />
        <polyline points="620,420 560,160 820,140 980,60" />
      </g>
      <g fill="#e9ddff">{STARS.map(([x, y]) => <circle key={`${x},${y}`} cx={x} cy={y} r="2.6" />)}</g>
      <circle cx="1500" cy="130" r="64" fill="#f3ead0" mask="url(#yir-t-moon)" filter="url(#yir-t-glow)" />
      <circle cx={cx + 20} cy={cy + 30} r="370" fill="#000" opacity=".6" filter="url(#yir-t-shadow)" />
      <circle cx={cx} cy={cy - 392} r="30" fill="none" stroke="url(#yir-t-rule)" strokeWidth="12" />
      <path d={`M${cx - 44} ${cy - 350} L${cx - 28} ${cy - 386} L${cx + 28} ${cy - 386} L${cx + 44} ${cy - 350} Z`} fill="url(#yir-t-brass)" />
      <circle cx={cx} cy={cy} r="362" fill="url(#yir-t-brass)" stroke="#4a3010" strokeWidth="3" />
      <circle cx={cx} cy={cy} r="282" fill="url(#yir-t-plate)" stroke="#4a3010" strokeWidth="3" />
      <g stroke="#3a2410" strokeWidth="2">
        {Array.from({ length: 72 }, (_, tick) => {
          const outer = onDial(tick * 5, 346);
          const inner = onDial(tick * 5, tick % 6 === 0 ? 318 : 334);
          return <line key={tick} x1={outer.x} y1={outer.y} x2={inner.x} y2={inner.y} />;
        })}
      </g>
      <g fontFamily="Cinzel, serif" fontWeight="700" fontSize="22" fill="#3a2410" letterSpacing="2">
        {MONTHS.map((name, month) => {
          const { x, y } = onDial(monthAngle(month), 300);
          return <text key={name} x={x.toFixed(1)} y={y.toFixed(1)} transform={`rotate(${month * 30 + 15} ${x.toFixed(1)} ${y.toFixed(1)})`} textAnchor="middle" dominantBaseline="middle">{name.toUpperCase()}</text>;
        })}
      </g>
      <g stroke="#e2c27a" strokeWidth="1.2" fill="none" opacity=".4">
        {[60, 110, 160, 210].map((radius, ring) => <circle key={radius} cx={cx} cy={cy + 40 - ring * 12} r={radius} />)}
        {Array.from({ length: 12 }, (_, spoke) => {
          const end = onDial(spoke * 30, 240);
          return <line key={spoke} x1={cx} y1={cy} x2={end.x} y2={end.y} />;
        })}
      </g>
      <g className="yir-spin">
        <circle cx={cx} cy={cy} r="240" fill="none" stroke="#e8cf8e" strokeWidth="3" opacity=".8" />
        <circle cx={cx} cy={cy - 46} r="176" fill="none" stroke="#e8cf8e" strokeWidth="8" />
        <circle cx={cx} cy={cy - 46} r="160" fill="none" stroke="#e8cf8e" strokeWidth="1.4" strokeDasharray="2 7" />
        <g transform={`translate(${cx} ${cy})`}>
          {Array.from({ length: 9 }, (_, pointer) => <path key={pointer} d="M0 -236 q14 26 0 56 q-10 -24 0 -56" transform={`rotate(${pointer * 40 + 10})`} fill="#e8cf8e" />)}
        </g>
      </g>
      <g>
        {months.map((count, month) => {
          if (!count) return null;
          const { x, y } = onDial(monthAngle(month), 262);
          return <circle key={month} cx={x.toFixed(1)} cy={y.toFixed(1)} r={4 + Math.min(count, 8) * 2.5} fill={month === busiest ? "#fff1b8" : "#c9a8ff"} filter="url(#yir-t-glow)" />;
        })}
      </g>
      <g transform={`rotate(${monthAngle(busiest ?? 0)} ${cx} ${cy})`}>
        <path d={`M${cx - 320} ${cy - 7} L${cx + 290} ${cy - 7} L${cx + 330} ${cy} L${cx + 290} ${cy + 7} L${cx - 320} ${cy + 7} Z`} fill="url(#yir-t-rule)" stroke="#4a3010" strokeWidth="1.5" />
      </g>
      <circle cx={cx} cy={cy} r="18" fill="url(#yir-t-brass)" stroke="#4a3010" strokeWidth="3" />
      <circle cx={cx} cy={cy} r="5" fill="#3a2410" />
    </svg>
  );
}

export function Crown() {
  return (
    <svg className="yir-crown" viewBox="0 0 64 44" fill="currentColor" aria-hidden="true">
      <path d="M4 38 L2 10 L18 24 L32 4 L46 24 L62 10 L60 38 Z" />
      <rect x="4" y="38" width="56" height="5" />
      <circle cx="2" cy="9" r="3" />
      <circle cx="32" cy="4" r="3.5" />
      <circle cx="62" cy="9" r="3" />
    </svg>
  );
}

// Drifting particles over the scene: stars, fireflies, embers or dust, by realm.
// Only where requestAnimationFrame exists and motion is allowed; tests and captures see a still frame.
export type ParticleMode = "stars" | "motes" | "embers" | "dust";

export function RealmParticles({ mode }: { mode: ParticleMode }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  useEffect(() => {
    const element = canvas.current;
    if (!element || typeof window.requestAnimationFrame !== "function" || prefersReducedMotion()) return;
    const context = element.getContext("2d");
    if (!context) return;
    let width = 0;
    let height = 0;
    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      width = element.clientWidth;
      height = element.clientHeight;
      element.width = width * ratio;
      element.height = height * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);
    const particles = Array.from({ length: 90 }, () => ({ x: Math.random(), y: Math.random(), size: Math.random(), speed: Math.random(), phase: Math.random() * 7 }));
    let tick = 0;
    let frame = 0;
    const draw = () => {
      tick += 1;
      context.clearRect(0, 0, width, height);
      for (const particle of particles) {
        const { x, y, size, speed, phase } = particle;
        switch (modeRef.current) {
          case "stars":
            if (y > 0.45) continue;
            context.globalAlpha = 0.2 + 0.6 * Math.abs(Math.sin(tick * 0.012 * (speed + 0.3) + phase));
            context.fillStyle = "#fff";
            context.beginPath();
            context.arc(x * width, y * height, 0.5 + size * 1.3, 0, 7);
            context.fill();
            break;
          case "motes":
            context.globalAlpha = 0.15 + 0.55 * Math.abs(Math.sin(tick * 0.02 + phase));
            context.fillStyle = "#b6ffcf";
            context.beginPath();
            context.arc(x * width + Math.sin(tick * 0.004 + phase) * 40, (((y * height - tick * 0.15 * (speed + 0.2)) % height) + height) % height, 1 + size * 2.2, 0, 7);
            context.fill();
            break;
          case "embers": {
            const rise = (((y * height - tick * (0.6 + speed * 1.4)) % (height + 40)) + height + 40) % (height + 40);
            context.globalAlpha = Math.min(1, rise / height) * 0.9;
            context.fillStyle = size > 0.6 ? "#ffd27a" : "#ff7a2a";
            context.fillRect((0.45 + x * 0.55) * width + Math.sin(tick * 0.02 + phase) * 14, rise, 1.5 + size * 2.2, 1.5 + size * 2.2);
            break;
          }
          default:
            context.globalAlpha = 0.1 + 0.35 * Math.abs(Math.sin(tick * 0.01 + phase));
            context.fillStyle = "#ffe7b0";
            context.beginPath();
            context.arc(x * width, (((y * height - tick * 0.2 * (speed + 0.1)) % height) + height) % height, 0.6 + size * 1.6, 0, 7);
            context.fill();
        }
      }
      context.globalAlpha = 1;
      frame = window.requestAnimationFrame(draw);
    };
    frame = window.requestAnimationFrame(draw);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
    };
  }, []);
  return <canvas className="yir-particles" ref={canvas} aria-hidden="true" />;
}
