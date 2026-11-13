# Wellfound Scraper by 2scraper

**Open-source Wellfound (AngelList Talent) job scraper for wellfound.com — three engines, your own infrastructure, 2Captcha's paid products only where they are actually needed.**

Pull startup job listings — title, company, company size and badges, salary AND equity ranges, remote configuration, years of experience, posting date and the full job description — straight from Wellfound into JSON or CSV.

[**View source on GitHub →**](https://github.com/2scraper/wellfound-scraper)

---

## What was actually measured

**You need one thing: a residential exit. Nothing else.**

Wellfound refuses a datacenter address on **every route**, `robots.txt` included. Measured on 2026-09-17 from a Hetzner VPS: HTTP **403** to plain HTTP, to headless Chromium and to headful Chromium alike. From a 2Captcha residential US exit, the same machine got HTTP **200** on `/`, `/jobs`, every `/role/…` shape and every job page — three times out of three.

Say that plainly instead of selling around it. A residential proxy is the one product this site actually requires, and it is one line in a `.env` file. Captcha solving, fingerprints and a hosted browser are all wired in, all optional, and most runs never reach them — because from a residential exit there is no challenge left to solve.

Full numbers are in the [repository README](https://github.com/2scraper/wellfound-scraper#readme).

## What you get

- Free, open-source scraper, one script per engine — **Playwright** (primary), **Selenium** and **Puppeteer** (via pyppeteer), plus a browserless client for 2Captcha's Scraper API. All three browser engines were run live against the same listing and returned **byte-identical rows**: the same 52 jobs, the same 38 columns, the same order.
- Three modes: a **role** landing page (the rich one, paginated), the **jobs** discovery feed, or a single **job** page.
- Reads Wellfound's own embedded payloads — the Next.js Apollo cache on a listing, the schema.org `JobPosting` on a job page — so there is no fragile DOM scraping anywhere in the primary path.
- JSON and CSV export, a documented 38-column `JobPosting` schema, and a `.meta.json` sidecar on every run recording status, pages completed and **Wellfound's own arithmetic**.
- 373 offline checks, fixtures cut from real captures and verified to parse identically to the untrimmed originals.
- Optional 2Captcha integration, wired in but never required beyond the exit.

## Four things about Wellfound worth knowing before you start

**A "page" is twenty companies, not twenty jobs.** `/role/r/software-engineer` reported `perPage: 20`, `pageCount: 47`, `totalStartupCount: 923` and `totalJobCount: 1881` — and its pages carried between 32 and 45 job rows each. Dividing 1,881 by 47 gives an answer that is wrong for every page, so the sidecar records both denominators.

**Asking past the last page does not fail — it repeats.** `?page=48` of a 47-page listing answers HTTP 200 carrying page 1's rows again. A run that trusted its own request would re-collect page 1 for as long as it was asked to and report success. This scraper plans against the site's stated `pageCount`, and reads back which page the server actually answered with.

**Pay is one rendered string, and the obvious parse is wrong three ways.** `$180k – $200k • 0.5% – 1.0%` splits salary from equity on a bullet — but either side may be missing, so 9 of 312 measured values are `No equity` alone and 2 are an equity range with no salary at all. `L` is the Indian lakh: `₹30L – ₹80L` is 3,000,000 to 8,000,000, not 30 to 80. And `No equity` is a statement the listing made, not a missing value.

**Gating is per route.** Role pages, the jobs feed and individual job pages are all served to a residential exit. Company profile pages are **not** — they answered 403 to plain HTTP and to a real browser on that same exit, three times each. This scraper has no mode for them, because there is nothing it could honestly offer.

## 2Captcha products, when you want them

| Product | What it's for on this site |
|---|---|
| **Residential proxies** | The one thing this site requires. A datacenter address gets HTTP 403 on every route, to every client tried. |
| **Scraping Browser API** | A remote browser you do not run or patch, with a chosen exit country and a persistent cookie profile. |
| **Captcha solving** | Cloudflare's managed challenge, if you meet one. It publishes no sitekey — it calls `turnstile.render()` once and keeps nothing — so this scraper hooks that call before any page script runs, and refuses to buy a task it could not build properly. Measured honestly: from a datacenter address the hook captured all four parameters and 2Captcha returned a token in 5–20 s, but **Cloudflare refused it** (3 tokens, 3 refusals). On this site the exit is what works, and it costs less. |
| **Fingerprints** | A consistent device identity for a local browser. |

One key, four separately-billed products: [2captcha.com](https://2captcha.com)

## What it deliberately does not do

Every route it accepts is allowed by Wellfound's published `robots.txt`, and every route those rules disallow has no mode here — checked by the offline suite against the published file, though not enforced as a runtime gate. It never submits Wellfound's apply or sign-up forms — an application filed by a scraper is a false record about a real person and a real company. There is no mode for candidate profiles (`/u/`, which `robots.txt` disallows), and no column anywhere for an individual's details. It defaults to a 2-second delay between pages.

---

MIT licensed. Not affiliated with or endorsed by Wellfound or AngelList.
