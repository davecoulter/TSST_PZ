# Candidate workflow: from detection to the system of record

Why this document exists: the pieces (the diff-imaging pipeline, its static pages, `/add_candidate/`, the STZ-PZ pages) are built by different people at different times. This records the workflow they serve and who owns each step, so decisions stay consistent. Written 2026-10-15 from a conversation with Dave and Justin. The features it drives are tracked in #16.

## The stages

```
machine detects   ->  human annotates   ->  triage in STZ-PZ  ->  promote   ->  follow-up  ->  system of record  ->  TNS
(Source Extractor     (static page: Save,    (real / bogus?        (becomes a    (observing)    (acquired data)       (post,
 on difference         confidence, notes,     watch list?           transient)                                         rename)
 images, cutouts,      tags)                  promote?)
 photometry, host)
```

| Stage | Owner | Where it lives |
|---|---|---|
| Detect, cut out, measure photometry, find a catalog host | the diff-imaging pipeline (Justin) | static pages (`.../diffpype_test/<run>/<field>/`), files on the central store |
| Surface detections, collect a quick human vote | the static page | the page plus its Save dialog (confidence, notes, tags) |
| Triage, light curves, SEDs, host, notes, tags, grouping | STZ-PZ candidate page | `/candidates/` and `/candidate/<slug>/` |
| Promote to a transient, follow-up, acquired data | STZ-PZ transient pages | `/transient_detail/<slug>/` |
| Report to the community | TNS | later (#29) |

## Separation of concerns

- **The pipeline and static page** know about images, photometry and the quick vote. They do not know what STZ-PZ stores internally: no database IDs, no enum values. They send names and URLs, never keys.
- **STZ-PZ** owns matching (a source within 0.2 arcsec of an existing one is the same object), history, tags, comments and promotion. It tells the client what happened (created, appended, warnings).
- **A candidate is a transient seen through its candidate data**, not a separate table. Status `Candidate` marks the triage stage. Promotion changes the status and nothing else, so the candidate page and its history never disappear. Each page links to the other.
- **Judgments are text for now.** A human's view of the source (real, maybe, not real; notes) is stored as a comment, not as an enum the database must mirror. A per-person label table is possible later (#35). `DataQuality` stays for measurement flags on photometry points (such as Superseded).
- **Tags are annotations for sorting, grouping and searching** (for example "everything with this tag goes on a NIRSpec MSA mask"). Candidate tags and transient tags are the same kind of record with a different `kind`, so the two meanings are not mixed.

## What moves between the stages (payload)

The contract is `agentic_planning/023-add-candidate-endpoint/contract.md` (v1.3). In short: one object per candidate (or an array); position, a permalink to the static page, a FitsMap link, the photometry per band and epoch with its cutout URLs, an optional catalog host, and the human's Save-dialog input (confidence, notes, tags). Re-sending replaces earlier points (they are flagged Superseded, not deleted).

## Triage page: first look, above the fold

1. Highest-S/N detection (its cutouts and values) and the latest detection.
2. Light curve, and an SED.
3. Host: catalog, ID, separation, photo-z.
4. Tags (candidate kind) and the comment thread, including the Save-dialog notes.
5. Links out: websniff page, FitsMap, FITS and region downloads (URLs on the central store, reachable on the VPN).

Below the fold: the runs that found it, who flagged it, and every image triplet. Clicking a photometry point should lead to its cutouts, so a reader can judge whether a measurement is trustworthy.

## Wish list, sorted

| Now (this branch) | Next | Later |
|---|---|---|
| payload v1.3 (host, notes, confidence, FitsMap, tags); host catalog and ID columns; candidate-kind tags; candidate page with links both ways | click a light-curve point to see its cutouts; FITS and region download links; SED refinements | host catalog loader (JADES and others) with its own schema (photo-z PDF, shapes, Kron photometry); probabilistic host association (GHOST, PROST) with a per-candidate-host table; per-person labels and rejection reasons (#35); promotion rules (#28); TNS (#29); group authorization if other groups use candidates |

## Known gaps and decisions on record

- A limit is a point with S/N < 3, worked out when a page renders. The JSON's `upper_limit` flag is read but not stored.
- Photometry rows created by `/add_candidate/` have no groups, so every logged-in user sees them. Group authorization is left for if other teams ever use the candidate framework.
- Hosts: one catalog per host for now. Overlapping catalogs (the same galaxy in two) need a catalog-entry table, planned with the catalog loader.
- The TESS and Thacher checks are switched off (#31).
- Security: HTTP basic auth over HTTP on the private network until tokens and TLS (#17).
- The static pages' host (`www.stsci.edu/~tsst`) is **reachable from the internet**. The PNG cutouts are already there; anything else symlinked into it (FITS files especially) is public too, so FITS stay copyable paths until a specific file is cleared.
- The payload's `mag` is the difference-image magnitude. One magnitude per filter is shown; the reference depth and the SCI and REF magnitudes are a later enhancement.

## Where things stand after the first build (2026-10-15)

What the stages look like inside STZ-PZ today. Details and the dated decisions are in `agentic_planning/027-candidate-pages/plan.md`.

- **Status is the lifecycle; tags are annotations.** Status `Candidate` is triage; `New` and the working statuses (Following, Watch, ...) are transients; `Archived` is kept but out of the way. A transient is always somewhere: a tag box or the **Needs review** grid on the main dashboard, the Candidates page, or the Archived page. Nothing is deleted.
- **`New` is a call to action, not the absence of tags.** Every created candidate gets the candidate-kind tag `New` (an import from the websniff page may bring tags, so "no tags" cannot mean "unseen"). Triage means removing it, with **Mark triaged** on the candidate page (which goes on to the next new candidate). A later post to the same candidate never puts it back.
- **`/candidates/` is a set of exclusive sub-grids**, like the main dashboard: **New** first (the backlog, in its own coloured box), then one grid per candidate tag, then **No tag**. The sidebar badge counts new candidates. A sortable table with a thumbnail, host redshift, detections, runs, reporters and a **score** (the average of each reporter's latest `quality_flag`; 1 definite, 2 probable, 3 possible).
- **`/candidate/<slug>/` is the triage page** (a view of the same transient, linked both ways with `/transient_detail/<slug>/`): the highest-S/N and most recent triplets, the host with a crosshair on its reference image, the SED (observed and rest frame), the light curve, flagged by, comments, candidate tags, an All cutouts grid like the websniff card, and the runs.
- **`/archived/`** is split by tag too (candidates and transients together; pipeline rows carry a badge), with a No tag grid.
- **Judgments are text for now** (the confidence and notes arrive as a comment by the posting user). A per-person label table is possible later (#35).
- **The posting user is the reviewer**, so each user posts with their own login (the CLI prompts for the password). Re-posting the same points supersedes them rather than duplicating.
- Hosts: one catalog per host (`HostCatalog` keyed by file name, `Host.catalog_object_id`); a later, different host is reported and not swapped in.

