// ASCII figures drawn from the product's own words, plus the small bits of page behaviour.
(() => {
  const STREAM =
    'ANYAPI · DATAFORSEO · GOANYAPI · TWITTERAPI.IO · YIR · $0.01500 · $0.09000 · X1.0 · X28 · QUOTE · RUN · --MAX-USD 0.1 · EXIT 2 · SERP.GOOGLE · X.SEARCH · KEYWORD.VOLUME · BACKLINKS.SUMMARY · IMAGE.GENERATE · ';
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const hash = (x, y, s) => {
    const v = Math.sin(x * 12.9898 + y * 78.233 + s * 37.719) * 43758.5453;
    return v - Math.floor(v);
  };
  // Cell kinds: 0 empty, 1 text, 2 inverted text, 3 grid dot.
  const grid = (x, y) => (x % 4 === 0 && y % 2 === 0 ? 3 : 0);

  // Five routes for one call, stepping down from the failover price to the cheapest.
  const stairs = (cols, rows) => {
    const levels = [0.13, 0.33, 0.49, 0.61, 0.69];
    const w = cols / 5;
    return (x, y) => {
      const i = Math.min(4, Math.floor(x / w));
      const top = Math.round(levels[i] * rows);
      if (i > 0 && x - Math.floor(i * w) < 2 && y >= Math.round(levels[i - 1] * rows) && y <= top) return 2;
      if (y === top) return 2;
      if (y > top) {
        if (hash(x >> 3, y, 1) < 0.035) return 2;
        return hash(x, y, 2) < 0.08 ? 0 : 1;
      }
      return grid(x, y);
    };
  };

  // Same job, five routes, dearest to cheapest; the cheapest is solid.
  const bars = (cols, rows) => {
    const hs = [0.9, 0.62, 0.44, 0.27, 0.12];
    const w = Math.floor((cols - 2) / 5) - 2;
    const base = rows - 2;
    return (x, y) => {
      for (let i = 0; i < 5; i++) {
        const x0 = 1 + i * (w + 2);
        const top = base - Math.round(hs[i] * (rows - 4));
        if (x >= x0 && x < x0 + w && y >= top && y <= base) {
          if (y === top || i === 4) return 2;
          return hash(x, y, 4) < 0.94 ? 1 : 0;
        }
      }
      return grid(x, y);
    };
  };

  // Paper dissolving into a dark band: 8-character blocks thin out away from the dark edge.
  const melt = (darkBelow) => (cols, rows) => (x, y) => {
    const p = darkBelow ? y / (rows - 1) : 1 - y / (rows - 1);
    if (p > 0.97) return 2;
    if (hash(x >> 3, y, darkBelow ? 6 : 7) < p * p * 0.9) return 2;
    if (hash(x, y, 8) < p * 0.45) return 1;
    return 0;
  };

  const DARK = { text: 'rgba(255,255,255,0.55)', dot: 'rgba(255,255,255,0.2)', invBg: '#f0ede6', invText: '#232323', bg: null };
  const PAPER = { text: '#232323', dot: 'rgba(35,35,35,0.3)', invBg: '#232323', invText: '#f0ede6', bg: '#f0ede6' };
  const CELL_H = 15;

  const fields = [...document.querySelectorAll('canvas[data-field]')].map((canvas) => {
    const name = canvas.dataset.field;
    const make = name === 'stairs' ? stairs : name === 'bars' ? bars : melt(canvas.dataset.dark === 'below');
    return { canvas, make, theme: name === 'melt' ? PAPER : DARK, off: 0, kind: null };
  });

  const draw = (f) => {
    const { canvas, theme } = f;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      f.kind = null;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = '13px "Geist Mono", ui-monospace, Menlo, monospace';
    ctx.textBaseline = 'top';
    const cw = ctx.measureText('M').width;
    const cols = Math.ceil(w / cw);
    const rows = Math.ceil(h / CELL_H);
    if (!f.kind || f.cols !== cols || f.rows !== rows) Object.assign(f, { kind: f.make(cols, rows), cols, rows });
    ctx.clearRect(0, 0, w, h);
    if (theme.bg) {
      ctx.fillStyle = theme.bg;
      ctx.fillRect(0, 0, w, h);
    }
    const inv = [];
    const text = [];
    const dots = [];
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const k = f.kind(x, y);
        if (!k) continue;
        if (k === 3) { dots.push(x, y); continue; }
        const ch = STREAM[(x + f.off + y * 41) % STREAM.length];
        if (k === 2) inv.push(x, y, ch);
        else if (ch !== ' ') text.push(x, y, ch);
      }
    }
    ctx.fillStyle = theme.invBg;
    for (let i = 0; i < inv.length; i += 3) ctx.fillRect(inv[i] * cw, inv[i + 1] * CELL_H, cw + 0.6, CELL_H);
    ctx.fillStyle = theme.invText;
    for (let i = 0; i < inv.length; i += 3) ctx.fillText(inv[i + 2], inv[i] * cw, inv[i + 1] * CELL_H + 1);
    ctx.fillStyle = theme.text;
    for (let i = 0; i < text.length; i += 3) ctx.fillText(text[i + 2], text[i] * cw, text[i + 1] * CELL_H + 1);
    ctx.fillStyle = theme.dot;
    for (let i = 0; i < dots.length; i += 2) ctx.fillText('·', dots[i] * cw, dots[i + 1] * CELL_H + 1);
  };

  // Size the footer wordmark so its ink spans exactly gutter to gutter.
  const mark = document.querySelector('.wordmark');
  const fitMark = () => {
    if (!mark) return;
    const cs = getComputedStyle(mark);
    const gutter = parseFloat(getComputedStyle(mark.nextElementSibling || mark).paddingLeft) || 0;
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.font = `${cs.fontWeight} 100px ${cs.fontFamily}`;
    const text = mark.textContent;
    const m = ctx.measureText(text);
    const em = (m.actualBoundingBoxLeft + m.actualBoundingBoxRight) / 100 + (parseFloat(cs.letterSpacing) / parseFloat(cs.fontSize)) * (text.length - 1);
    const size = (mark.clientWidth - 2 * gutter) / em;
    mark.style.fontSize = `${size}px`;
    mark.style.paddingLeft = `${gutter + (m.actualBoundingBoxLeft / 100) * size}px`;
  };

  const drawAll = () => { fields.forEach(draw); fitMark(); };
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(drawAll);
  let resizeTimer;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawAll, 120);
  });

  // The hero figure's text flows while it is on screen.
  const live = fields.filter((f) => f.canvas.hasAttribute('data-animate'));
  if (!still && live.length) {
    const visible = new Set();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) e.isIntersecting ? visible.add(e.target) : visible.delete(e.target);
    });
    live.forEach((f) => io.observe(f.canvas));
    setInterval(() => {
      if (document.hidden) return;
      for (const f of live) {
        if (!visible.has(f.canvas)) continue;
        f.off = (f.off + 1) % STREAM.length;
        draw(f);
      }
    }, 140);
  }

  // ~28× counts up once, and the receipt prints line by line, when they scroll in.
  const once = (el, fn) => {
    const io = new IntersectionObserver((entries) => {
      if (!entries[0].isIntersecting) return;
      io.disconnect();
      fn();
    }, { threshold: 0.35 });
    io.observe(el);
  };
  document.querySelectorAll('[data-reveal]').forEach((el) => once(el, () => el.classList.add('in')));
  if (!still) {
    document.querySelectorAll('[data-count]').forEach((el) => {
      const to = Number(el.dataset.count);
      el.textContent = '1';
      const io = new IntersectionObserver((entries) => {
        const e = entries[0];
        // Jumped past it (an anchor link): show the final number without counting.
        if (!e.isIntersecting && e.boundingClientRect.top < 0) {
          io.disconnect();
          el.textContent = String(to);
          return;
        }
        if (!e.isIntersecting) return;
        io.disconnect();
        const t0 = performance.now();
        const step = (t) => {
          const p = Math.min(1, (t - t0) / 1100);
          el.textContent = String(Math.max(1, Math.round(to * (1 - (1 - p) ** 3))));
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }, { threshold: 0.35 });
      io.observe(el);
    });
  }

  // Remember which language home the visitor reads, so links home from the English-only pages keep it.
  const here = document.querySelector('a[hreflang][aria-current="page"]');
  let home = null;
  try {
    if (here) localStorage.setItem('lang-home', here.getAttribute('href'));
    else home = localStorage.getItem('lang-home');
  } catch {}
  if (home && /^\/[a-z]{2}\/$/.test(home)) {
    document.querySelectorAll('a[href="/"], a[href^="/#"]').forEach((a) => {
      a.setAttribute('href', home + a.getAttribute('href').slice(1));
    });
  }

  // Offer this page in the browser's preferred language, once: never redirect, and stay quiet after the visitor
  // switches, closes the prompt or picks from a language menu. The first preferred language this page has wins.
  const OFFER = 'lang-offer';
  const remember = () => { try { localStorage.setItem(OFFER, 'off'); } catch {} };
  const copies = new Map();
  document.querySelectorAll('a[hreflang][data-offer]').forEach((a) => {
    copies.set(a.getAttribute('hreflang').split('-')[0], a);
    a.addEventListener('click', remember);
  });
  // Crawlers render with an English browser; keep the prompt out of what they index for the other languages.
  let quiet = /bot|crawl|spider|slurp|lighthouse/i.test(navigator.userAgent);
  try { quiet ||= localStorage.getItem(OFFER) === 'off'; } catch {}
  const current = document.documentElement.lang.split('-')[0];
  const wanted = (navigator.languages || [navigator.language || '']).map((l) => l.split('-')[0].toLowerCase()).find((l) => copies.has(l));
  if (!quiet && wanted && wanted !== current) {
    const link = copies.get(wanted);
    const box = document.createElement('aside');
    box.className = 'lang-offer mono';
    box.lang = link.lang;
    box.innerHTML = '<p></p><a></a><button type="button">×</button>';
    box.querySelector('p').textContent = link.dataset.offer;
    const go = box.querySelector('a');
    go.href = link.getAttribute('href') + location.hash;
    go.hreflang = link.lang;
    go.textContent = `${link.dataset.switch} →`;
    go.addEventListener('click', remember);
    const close = box.querySelector('button');
    close.setAttribute('aria-label', link.dataset.close);
    close.addEventListener('click', () => { remember(); box.remove(); });
    document.body.append(box);
    // Step aside at the foot of the page, where it would cover the footer's own language menu.
    const foot = document.querySelector('.foot-bar');
    if (foot) new IntersectionObserver((entries) => box.classList.toggle('away', entries[0].isIntersecting)).observe(foot);
  }

  // Nav: the phone menu.
  const pill = document.querySelector('.pill');
  const menu = document.querySelector('.menu');
  menu.addEventListener('click', () => {
    const open = pill.classList.toggle('open');
    menu.setAttribute('aria-expanded', String(open));
  });
  const closeMenu = () => {
    pill.classList.remove('open');
    menu.setAttribute('aria-expanded', 'false');
  };
  document.querySelectorAll('#navlinks a').forEach((a) => a.addEventListener('click', closeMenu));
  // Esc or a tap outside closes the phone menu and any open language menu.
  const closeAll = (keep) => {
    if (!pill.contains(keep)) closeMenu();
    document.querySelectorAll('details.lang[open]').forEach((d) => { if (!d.contains(keep)) d.open = false; });
  };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAll(null); });
  document.addEventListener('click', (e) => closeAll(e.target));

  // Copy the install command.
  document.querySelectorAll('[data-copy]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const label = btn.querySelector('[data-copy-label]') || btn.parentElement.querySelector('[data-copy-label]');
      const was = label ? label.textContent : '';
      const say = (text) => {
        if (!label) return;
        label.textContent = text;
        setTimeout(() => { label.textContent = was; }, 1500);
      };
      // No clipboard (plain http, permission denied): select the command shown next to the button so it can be copied by hand.
      const failed = () => {
        say(btn.dataset.failed || 'copy failed');
        const code = btn.parentElement.querySelector('code') || document.querySelector('.cmd-line');
        if (code) getSelection().selectAllChildren(code);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(btn.dataset.copy).then(() => say(btn.dataset.copied || 'copied'), failed);
      else failed();
    });
  });
})();
