# Aladin Lite 3.8.2 (vendored, #70)

Served from our own static files so a page load never depends on CDS's hosting of the library
(plan: `agentic_planning/070-aladin-v3/plan.md`). Only sky tiles and lookups still come from CDS,
after the page has rendered.

- **Source:** npm `aladin-lite@3.8.2`, `https://registry.npmjs.org/aladin-lite/-/aladin-lite-3.8.2.tgz`
- **Integrity:** `sha512-/VGtxSWZ4StdKgwjmzqNkUY/3iTaBZJ5F6bN+nAfcK1NEATcAb2CYJX4U8FElpwYMgKrypYQV5KniRzhVbH+nA==`
  (npm's published value, checked on download 2026-11-12; sha1 `53a52804ab556fbcfffb42f72320fa5a33c4bd4e`)
- **File:** `aladin.js` is the package's `dist/aladin.js`, unmodified: one ES module (`export default`),
  with its CSS and WebAssembly embedded. `A.init` is a promise; it needs WebGL2.
- **Licence:** GPL-3 (`package.json`); the package ships `COPYING` (GPL-3) and `LICENSE` / `COPYING.LESSER` (LGPL-3), kept here.
- **Loaded by:** `YSE_App/templates/YSE_App/aladin_loader.html`.
- **To upgrade:** download the new tarball, check its integrity against `npm view aladin-lite@<v> dist.integrity`,
  copy `dist/aladin.js` and the licence files into a new `aladin-lite/<v>/` folder, point the loader at it.
- **Deploy:** run `manage.py collectstatic` so nginx serves it (it serves `STATIC_ROOT`).
