/**
 * Local, self-made pages for the recipe run-report tests. No network, no real Facebook/Instagram.
 *
 * The fixtures mimic ONLY the DOM shape the recipes act on (a composer control, a contenteditable
 * caption, a hidden <input type=file>, Next/Post/Share/Done buttons, a <video> preview), so a
 * recipe can be driven end-to-end in seconds against a deterministic page. They deliberately let
 * a test BREAK one step (the caption never lands, the preview never appears), which is what
 * proves the recipe records the failure instead of reporting a quiet success.
 */

/** Serve a fixture as a data: URL (no server, no network). */
export const dataUrl = (html: string): string => `data:text/html,${encodeURIComponent(html)}`;

/** File input paths must be absolute. On Windows Chrome wants a POSIX-style "/d/..." path. */
export function uploadPathFor(file: string): string {
  if (process.platform !== "win32") return file;
  return "/" + file.replace(/^([A-Za-z]):/, (_m, drive) => drive.toLowerCase()).replace(/\\/g, "/");
}

export interface FbFixtureOptions {
  /**
   * false => the caption box exists and takes keystrokes, but reverts every change (a controlled
   * component whose state never commits). This is the real "typed but never landed" failure.
   */
  captionLands?: boolean;
  /** false => the file input fires `change` but no <video> preview ever renders. */
  preview?: boolean;
  /** Text the Reels tab shows; the recipe's own post-publish verification reads it. */
  reelsTabText?: string;
}

/**
 * Facebook fixture. The Page URL is the fixture itself; appending `&sk=reels_tab` (what the
 * recipe does for verification) switches the rendered content to the Reels tab.
 */
export function facebookFixture(opts: FbFixtureOptions = {}): string {
  const captionLands = opts.captionLands !== false;
  const preview = opts.preview !== false;
  const reelsText = opts.reelsTabText ?? "";
  return `<!doctype html><meta charset="utf-8"><title>Facebook fixture</title>
<style>body{font-family:sans-serif;margin:20px}</style>
<div role="main" id="main"></div>
<script>
const CAPTION_LANDS = ${captionLands}, PREVIEW = ${preview};
const REELS_TEXT = ${JSON.stringify(reelsText)};
const main = document.getElementById('main');
// For a data: URL there is no query string, so the recipe's "&sk=reels_tab" lands inside the
// payload; checking href covers both that and a real ?sk=reels_tab URL.
const isReelsTab = () => location.href.includes('sk=reels_tab');

function showPage() {
  document.body.insertAdjacentHTML('beforeend',
    '<button id="decline" onclick="this.remove()">Decline optional cookies</button>' +
    '<button id="composer" aria-label="What\\'s on your mind?">What\\'s on your mind?</button>');
  document.getElementById('composer').onclick = openComposer;
}

function openComposer() {
  document.getElementById('composer')?.remove();
  const d = document.createElement('div');
  d.setAttribute('role', 'dialog');
  d.innerHTML =
    '<div id="cap" role="textbox" contenteditable="true" aria-label="What\\'s on your mind?" ' +
    'style="width:340px;height:90px;border:1px solid #888"></div>' +
    '<input id="fi" type="file" accept="video/*" style="display:none">' +
    '<button id="next">Next</button><button id="post">Post</button>';
  document.body.appendChild(d);

  if (!CAPTION_LANDS) {
    // Accepts the keystrokes, then discards them — React state never commits.
    const cap = d.querySelector('#cap');
    cap.addEventListener('input', () => { cap.textContent = ''; });
  }

  const fi = d.querySelector('#fi');
  fi.onchange = () => {
    if (!PREVIEW) return;
    const v = document.createElement('video');
    v.width = 120; v.height = 160;
    d.appendChild(v);
  };
  // The terminal Post navigates to the Reels tab, like the real Page does after publishing.
  d.querySelector('#post').addEventListener('click', () => {
    location.href = location.href + '&sk=reels_tab';
  });
}

if (isReelsTab()) main.textContent = REELS_TEXT;
else showPage();
</script>`;
}

export interface IgFixtureOptions {
  /** false => the caption box accepts keystrokes then discards them. */
  captionLands?: boolean;
  /** false => Done never appears after Share. */
  done?: boolean;
}

/**
 * Instagram fixture: home -> "New post" -> Post -> upload -> Next (crop) -> Next (edit) ->
 * caption -> Share -> Done. Every control the recipe targets is present by default.
 */
export function instagramFixture(opts: IgFixtureOptions = {}): string {
  const captionLands = opts.captionLands !== false;
  const done = opts.done !== false;
  return `<!doctype html><meta charset="utf-8"><title>Instagram fixture</title>
<style>body{font-family:sans-serif;margin:20px}</style>
<div role="main" id="main"></div>
<script>
const CAPTION_LANDS = ${captionLands}, SHOW_DONE = ${done};
const body = document.body;

body.insertAdjacentHTML('beforeend',
  '<svg aria-label="New post" width="24" height="24"><rect width="24" height="24"></rect></svg>');
body.querySelector('svg[aria-label="New post"]').addEventListener('click', openMenu);

function openMenu() {
  const m = document.createElement('div');
  m.innerHTML = '<div role="button" id="m-post" style="width:90px">Post</div>' +
                '<div role="button" id="m-live" style="width:90px">Live video</div>';
  body.appendChild(m);
  m.querySelector('#m-post').addEventListener('click', openUpload);
}

function openUpload() {
  const d = document.createElement('div');
  d.innerHTML = '<input id="fi" type="file" style="display:none"><button id="next1">Next</button>';
  body.appendChild(d);
  d.querySelector('#fi').onchange = () => {};
  d.querySelector('#next1').addEventListener('click', () => { d.remove(); openEdit(); });
}

function openEdit() {
  const d = document.createElement('div');
  d.innerHTML = '<button id="next2">Next</button>';
  body.appendChild(d);
  d.querySelector('#next2').addEventListener('click', () => { d.remove(); openShare(); });
}

function openShare() {
  const d = document.createElement('div');
  d.innerHTML =
    '<div id="cap" role="textbox" contenteditable="true" aria-label="Write a caption..." ' +
    'style="width:340px;height:90px;border:1px solid #888"></div>' +
    '<button id="share">Share</button>';
  body.appendChild(d);
  if (!CAPTION_LANDS) {
    const cap = d.querySelector('#cap');
    cap.addEventListener('input', () => { cap.textContent = ''; });
  }
  d.querySelector('#share').addEventListener('click', () => {
    d.remove();
    if (SHOW_DONE) body.insertAdjacentHTML('beforeend', '<div role="button" id="done">Done</div>');
  });
}
</script>`;
}
