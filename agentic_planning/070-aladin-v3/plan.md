# 070: Replace Aladin Lite v2 with vendored Aladin Lite v3

- **Issue:** #70
- **Branch:** `claude/project-thread-lh91gc`. This is the Project Claude working branch; the convention would be `70-aladin-v3`, so rename it before the PR if you want.
- **Status:** Draft

## Why
On the public site (`https://stzpz.stsci.edu`), pages that embed Aladin take tens of seconds to load. Every one of them pulls Aladin Lite **v2** from CDS at render time:

```html
<link rel="stylesheet" href="//aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.css" />
<script src="//aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.js"></script>
```

On 2026-10-29 those URLs hung from off-VPN, over https and http, and on `aladin.cds.unistra.fr` too. The stylesheet is in `<head>`, so the page can't paint until it loads or times out. DevTools showed our own static files done in about 1s, and `/dashboard/` (no Aladin) loads fast. v2 is also unmaintained.

Dave chose to go straight to v3 rather than a v2 stopgap. That means the Aladin pages stay slow until this lands.

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
| 4 | Port transient summary | v3 is WebGL, and browsers cap live WebGL contexts at ~16 per page, so one viewer per transient won't scale. Default: create each viewer lazily when its div scrolls into view (IntersectionObserver), and run the same hook for AJAX-loaded pages. See open question 1. |
| 5 | Port YSE sky | In v3, `getViewDataURL()` returns a **Promise** and the colormap API changed. Rework the 1s poll and the colormap reversal. See open question 2. |
| 6 | Remove all v2 references; fix the jquery include | Point it at the jQuery we already serve from `/static/`. |

Out of scope: other external CDN includes (fonts.googleapis, oss.maxcdn, etc.), a broader frontend modernization, and Python/Docker image dependencies (none change).

## Design notes
- **Why vendor rather than use CDS's hosted v3:** the outage is CDS's hosting. With the library served from our nginx, the only CDS dependency left is HiPS tiles, which load asynchronously after the page renders. If CDS is down, the viewer is blank and the rest of the page is unaffected.
- **ES module:** the npm build is `export default A`, so it loads with `<script type="module">` (deferred by default, never render-blocking). All target browsers support modules.
- **Alternative for thumbnails:** for places that just show a static picture (the summary list, the yse_sky background), CDS's `hips2fits` service returns a JPEG for a given ra/dec/fov/size as a plain `<img>`. That avoids WebGL entirely, but it's a CDS dependency per image (still non-blocking). It's an option, not the default.

## Acceptance criteria
- [ ] No template references `aladin.u-strasbg.fr` or `AladinLite/api/v2`; `grep -rn "api/v2" YSE_App/templates` is empty.
- [ ] Transient detail, transient summary (first page and an AJAX-loaded page), and YSE sky show the DSS2 sky via v3.
- [ ] With CDS blocked (DevTools → request blocking `*cds.unistra.fr*`, `*u-strasbg.fr*`), all three pages render immediately and their other JS (date pickers, tables, paper.js) works. Only the sky area is blank.
- [ ] Off-VPN, public `transient_detail` loads in about the same time as `/dashboard/`.
- [ ] A transient summary page with >16 transients shows no WebGL context-lost errors in the console.
- [ ] No mixed-content warnings on these pages over https.
- [ ] `ruff check .` is still clean (no Python change expected).

## Verification
Local stack: `docker compose up`, log in, open a transient detail page, `/transient_summary/<status>/` (scroll to trigger lazy init plus the next AJAX page), and `/yse_sky/`. Repeat with CDS request-blocked. Then do the same against prod off-VPN after deploy, comparing DevTools Network timings with `/dashboard/`.

## Open questions
1. **Transient summary:** lazy interactive v3 viewers (default), or static `hips2fits` JPEGs with a click-to-open interactive viewer?
2. **YSE sky:** keep a hidden v3 instance as the image source (async `getViewDataURL`), or replace it with one `hips2fits` image request when the field changes? The latter is simpler and drops the 1s poll.
3. Is any other page outside `YSE_App/templates` (e.g. the Explorer or admin) using Aladin? None found by grep.

## Log
- **2026-10-29:** The slow public pages were traced to CDS-hosted Aladin v2 hanging, not to SSO/DNS or Django (thread with Dave). Dave chose v3 directly over a v2 non-blocking stopgap. `aladin-lite` 3.8.2 confirmed on npm as a single ES-module `dist/aladin.js` (GPL-3).
