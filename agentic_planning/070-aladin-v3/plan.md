# 070: Replace Aladin Lite v2 with vendored Aladin Lite v3

- **Issue:** #70
- **Branch:** `70-aladin-v3`
- **Status:** Approved by Dave 2026-11-12, with the decisions below. Local Claude took over the branch from Project Claude (2026-11-12). Building waits for Dave to switch to Opus 5.5 at medium effort.

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
- [ ] No template references `aladin.u-strasbg.fr` or `AladinLite/api/v2`; `grep -rn "api/v2" YSE_App/templates` is empty.
- [ ] Transient detail, transient summary (first page and an AJAX-loaded page), and YSE sky show the DSS2 sky via v3.
- [ ] With CDS blocked (DevTools → request blocking `*cds.unistra.fr*`, `*u-strasbg.fr*`), all three pages render immediately and their other JS (date pickers, tables, paper.js) works. Only the sky area is blank.
- [ ] Off-VPN, public `transient_detail` loads in about the same time as `/dashboard/`.
- [ ] The transient summary page shows `hips2fits` thumbnails (lazy, linking to the transient page) and loads no Aladin library and no WebGL viewer.
- [ ] No mixed-content warnings on these pages over https.
- [ ] `ruff check .` is still clean (no Python change expected).

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
