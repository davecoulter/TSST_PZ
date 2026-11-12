# 070: Replace Aladin Lite v2 with vendored Aladin Lite v3

- **Issue:** #70
- **Branch:** `70-aladin-v3`
- **Status:** Built and tested locally 2026-11-12 (Opus 5.5 at medium); PR opened. Approved by Dave 2026-11-12 with the decisions below. Local Claude took over the branch from Project Claude.

## Why
On the public site (`https://stzpz.stsci.edu`), pages that embed Aladin take tens of seconds to load. Every one of them pulls Aladin Lite **v2** from CDS at render time:

```html
<link rel="stylesheet" href="//aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.css" />
<script src="//aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.js"></script>
```

On 2026-10-29 those URLs hung from off-VPN, over https and http, and on `aladin.cds.unistra.fr` too. The stylesheet is in `<head>`, so the page can't paint until it loads or times out. DevTools showed our own static files done in about 1s, and `/dashboard/` (no Aladin) loads fast. v2 is also unmaintained.

Dave chose to go straight to v3 rather than a v2 stopgap. That means the Aladin pages stay slow until this lands.

It also breaks the pages, not only slows them (2026-11-11, #52's testing): with CDS unreachable, `A.aladin(...)` throws in `transient_detail.html`'s startup function, and every handler set up after it is never attached, including the status buttons (they silently do nothing). This now blocks the production deploy (Dave).

## Current usage (v2)
| Page | Template(s) | How Aladin is used |
|---|---|---|
| Transient detail | `transient_detail.html` (CSS l.9, JS l.1165, `A.aladin` l.1473) | One interactive 240×240 DSS2 cutout. Init runs in the middle of the page's `$(function(){…})`, so if `A` is undefined it throws and kills the init that follows (daterangepicker etc.). |
| Transient summary | `transient_summary.html` (CSS l.11, JS l.104) + `transient_summary_individual.html` (`A.aladin` l.376, inside a `{% for %}`) | **One instance per transient on the page** (400×400). Paginated pages arrive via AJAX (`transient_summary_paginate.html`), so their init has to run on insert. |
| YSE sky | `yse_sky/header.html` (CSS/JS l.156–157, instance l.456, poll l.411) | A hidden instance used only as an image source: `aladin.getViewDataURL()` every 1s → `<img id="backgroundSky">` → paper.js canvas. The colormap is reversed. |

Related: `transient_summary.html:94` loads `http://code.jquery.com/jquery-latest.js`, which is blocked as mixed content on https. It gets fixed in the same pass.

## Scope
| # | Deliverable | Notes |
|---|---|---|
| 1 | Vendor `aladin-lite@3.8.2` `dist/aladin.js` into `YSE_App/static/YSE_App/aladin-lite/3.8.2/` | It's the latest stable release (2026-03-06) and GPL-3, same as this repo. It's a single 2.4 MB ES module with CSS and WASM bundled in. Pull it from the npm tarball once (no npm in the image, no build step), keep `LICENSE`, and record the version and sha in a `README`. Same precedent as the vendored `bokeh-*.min.js`. |
| 2 | A shared partial `YSE_App/aladin_loader.html` | It loads the module with `<script type="module">`, awaits `A.init`, and exposes a promise (`window.aladinReady`) that pages chain on. Not render-blocking, and pages don't each reimplement it. |
| 3 | Port transient detail | `aladinReady.then(A => A.aladin('#aladin-lite-div', {survey: 'P/DSS2/color', fov: 0.017, target: …}))`, moved out of the main init block so a failure can't break the other widgets. |
| 4 | Transient summary: static thumbnails (decision 1) | Each transient gets a `hips2fits` JPEG as a plain `<img loading="lazy">` (CDS's `hips2fits` service renders a HiPS cutout for an ra/dec/fov/size), linking to its transient page, which keeps the interactive viewer. No Aladin and no WebGL on this page, so no ~16-context limit; AJAX-loaded pages need no init hook. |
| 5 | YSE sky: one static image (decision 2) | The hidden Aladin instance and its 1 s `getViewDataURL()` poll become one `hips2fits` image request when the field changes, feeding the same `<img id="backgroundSky">` for paper.js. The reversed colormap: check what `hips2fits` offers, else a CSS `filter: invert(1)`. |
| 6 | Remove all v2 references; fix the jquery include | Point it at the jQuery we already serve from `/static/`. Delete `transient_detail.html.bkp`, an old committed backup of the YSE page that nothing references but that still loads v2. |

Out of scope: reclaiming the YSE sky page to show the spatial distribution of the transients in STZ-PZ (Dave, 2026-11-12: a future use for the page, its own issue). Other external CDN includes (fonts.googleapis, oss.maxcdn, etc.), a broader frontend modernization, and Python/Docker image dependencies (none change).

## Design notes
- **Why vendor rather than use CDS's hosted v3:** the outage is CDS's hosting. With the library served from our nginx, the only CDS dependency left is HiPS tiles, which load asynchronously after the page renders. If CDS is down, the viewer is blank and the rest of the page is unaffected.
- **ES module:** the npm build is `export default A`, so it loads with `<script type="module">` (deferred by default, never render-blocking). All target browsers support modules.
- **Alternative for thumbnails:** for places that just show a static picture (the summary list, the yse_sky background), CDS's `hips2fits` service returns a JPEG for a given ra/dec/fov/size as a plain `<img>`. That avoids WebGL entirely, but it's a CDS dependency per image (still non-blocking). It's an option, not the default.

## Acceptance criteria
- [x] No template references `aladin.u-strasbg.fr` or `AladinLite/api/v2`; `grep -rn "api/v2" YSE_App/templates` is empty.
- [ ] Transient detail, transient summary (first page and an AJAX-loaded page), and YSE sky show the DSS2 sky via v3. *Not seen yet: CDS's image hosting was down throughout 2026-11-12. The v3 library loads and runs (WebGL2), and the summary and sky pages use `hips2fits` (decisions 1-2). Check once CDS is back.*
- [x] With CDS blocked (DevTools → request blocking `*cds.unistra.fr*`, `*u-strasbg.fr*`), all three pages render immediately and their other JS (date pickers, tables, paper.js) works. Only the sky area is blank.
- [ ] Off-VPN, public `transient_detail` loads in about the same time as `/dashboard/`. *Measured after the production deploy.*
- [x] The transient summary page shows `hips2fits` thumbnails (lazy, linking to the transient page) and loads no Aladin library and no WebGL viewer.
- [ ] No mixed-content warnings on these pages over https. *Partly: the `jquery-latest` include is gone, but the SDSS (`skyservice.pha.jhu.edu`) and Legacy Survey (`legacysurvey.org`) cutouts are still requested over `http://`. They predate #70; added to #80.*
- [x] `ruff check .` is still clean (no Python change expected).

## Verification
Local stack: `docker compose up`, log in, open a transient detail page, `/transient_summary/<status>/` (scroll to trigger lazy init plus the next AJAX page), and `/yse_sky/`. Repeat with CDS request-blocked. Then do the same against prod off-VPN after deploy, comparing DevTools Network timings with `/dashboard/`.

## Decisions (Dave, 2026-11-12)
1. **Transient summary:** static `hips2fits` thumbnails, each linking to its transient page (which keeps the interactive v3 viewer). No WebGL limit, no 2.4 MB library on a list page, and images never block the page.
2. **YSE sky:** one `hips2fits` image too, so the approach is the same everywhere. The 2.4 MB v3 library is then needed on the transient page only.
3. **Other pages:** none. A 2026-11-12 grep finds Aladin only in the three pages above, a comment in `views.py`, and `transient_detail.html.bkp` (deleted, scope 6).
4. **Dependency:** Dave approves vendoring `aladin-lite` 3.8.2 (still the latest stable on npm, 2026-11-12; 3.9.2 is a beta). No Python or Docker image change.

## Log
- **2026-10-29:** The slow public pages were traced to CDS-hosted Aladin v2 hanging, not to SSO/DNS or Django (thread with Dave). Dave chose v3 directly over a v2 non-blocking stopgap. `aladin-lite` 3.8.2 confirmed on npm as a single ES-module `dist/aladin.js` (GPL-3).
- **2026-11-12:** Local Claude took over the branch and merged `master` (with #52, PR #77). Dave's decisions recorded: `hips2fits` thumbnails on the summary page and the YSE sky page, v3 only on the transient page; the vendored dependency approved. #70 now blocks the production deploy: with CDS unreachable, the transient page's buttons stop working (found in #52's testing). Model and effort: Opus 5.5 at medium.
- **2026-11-12 (built, Opus 5.5 at medium):**
  - **Vendored** `aladin-lite` 3.8.2 from npm into `YSE_App/static/YSE_App/aladin-lite/3.8.2/`. The integrity hash was checked against npm's published sha512. `aladin.js` is unmodified: one ES module with its WebAssembly embedded, needing WebGL2. The package declares GPL-3 and ships the GPL and LGPL texts, all kept. A README records the source, the hashes and how to upgrade, and a test pins the file's sha1.
  - **`aladin_loader.html`:** a classic script defines `window.aladinReady` (a promise), then a module script imports our copy and resolves it after `A.init`. A failed load or no WebGL2 rejects it, with a console warning, and nothing else on the page is affected.
  - **Transient page:** the v2 stylesheet in `<head>` and the v2 script are gone; `A.aladin` runs in `aladinReady.then(...)`, so it can no longer throw inside the page's startup function.
  - **Summary page and YSE sky page:** static DSS2 cutouts from `hips2fits` (`templatetags/sky_extras.py`, one URL builder; parameter names taken from Aladin's own code), lazy-loaded on the summary page and linking to the transient page. The sky page's hidden viewer and its 1 s poll are gone. Its reversed colour map is dropped: the picture is drawn onto a canvas, where CSS can't invert it, and this is a legacy page.
  - **jQuery:** the summary page's `http://code.jquery.com/jquery-latest.js` was **removed**, not repointed. `base.html` already loads our jQuery first, and a second copy would drop the plugins attached to it (on https it was blocked as mixed content anyway).
  - Deleted `transient_detail.html.bkp`.
  - **Deploy:** run `manage.py collectstatic`. nginx serves `STATIC_ROOT` (`YSE_PZ/static`), and the startup script has it commented out.
  - **Found:**
    - CDS's image service was unavailable during the build: "Page unavailable", backup host timing out. So no real cutout was seen yet, which is exactly the outage this change makes harmless.
    - nginx compresses nothing: `aladin.js` is 2.39 MB on a first visit, 0.84 MB compressed. Later visits revalidate with ETag/Last-Modified. Compression is proposed to Dave, awaiting his OK.
  - 163 `YSE_App` tests pass; `ruff check .` passes.
- **2026-11-12 (Dave's OK): compression on** in `docker/nginx/default.conf`, at the server level (`gzip on`, for CSS, JS, JSON, XML, SVG and text, plus HTML; `gzip_proxied any` covers Django's pages). Measured: `aladin.js` 2.39 MB to 0.85 MB, Bokeh 0.80 to 0.25 MB, AdminLTE CSS 92 to 15 KB. **Deploy:** restart nginx. The config is bind-mounted as a single file, so a container started before an edit keeps the old copy.
- **2026-11-12 (Dave's browser check, CDS down):** v3 loaded and ran (WebGL2 fine), every Aladin error was asynchronous, and **the status buttons work** with CDS unreachable: the deploy blocker is gone. Two fixes from his console:
  - **Aladin reported usage to CDS:** `log` defaults to on, and its logger sends `window.location.href` and the referer to `alasky.unistra.fr/cgi/AladinLiteLogger`. Now `log: false`.
  - **The survey lookup kept retrying:** given the name `P/DSS2/color`, v3 asks CDS's registry on two mirrors, then tries the name as a path on this site (404), over and over while CDS is down. Given an address (`https://alasky.cds.unistra.fr/DSS/DSSColor`), it makes one request for the survey's description, and gives one error at most.
  - A test pins both.
  - **Still looping after that:** Aladin's `hipsList` option defaults to its built-in list of favourite surveys (DSS2 colour first, by name), and it looks each one up at start-up: the same registry and local-path loop, separate from the survey shown. Now `hipsList: []` (the code takes `options.hipsList || DEFAULT`, and an empty list counts as given). Pinned in the test too.
  - **And still:** when a viewer's only survey fails, Aladin 3.8.2 falls back to `DEFAULT_OPTIONS.survey` (`P/DSS2/color`, by name) in a `finally`, which fails too and falls back again, forever, and no option turns it off. So `aladin_loader.html` now has `window.aladinView(selector, options)`. It fetches the survey's `properties` once (5 s timeout; CDS allows it, `Access-Control-Allow-Origin: *`), creates the viewer only if that answers, with `log: false` and `hipsList: []` always, and otherwise writes "Sky view unavailable: CDS is not responding" in the box. The transient page uses it; the vendored file stays unmodified.
  - **Why DSS2 failed (Dave asked):** not deprecated. CDS's sky-image hosting (`alasky.cds.unistra.fr`) was down: DSS2 and 2MASS `properties` both 404, Simbad 404, while `cds.unistra.fr` and the registry answered. Aladin 3.8.2's built-in registry mirrors use `alasky.unistra.fr` and `alaskybis.unistra.fr`; the first does not resolve, the second timed out. Passing the survey as a `cds.unistra.fr` address avoids them.
- **2026-11-12 (ready to merge):** 164 `YSE_App` tests pass; `ruff check .` passes; no v2 Aladin reference left. Dave's real-outage check: the transient page shows "Sky view unavailable", with one failed request and one warning, and its status buttons work. Two criteria wait: seeing the sky once CDS is back, and the production load-time comparison.
