# Evidence and verification

Historical evidence review: 14 September 2026. The
[16 September verification and source release](verification-2026-09-16.md)
supersedes the source-availability and latest-check statements below.

## Reproduce the checks

Run from the repository root:

```bash
python3 scripts/verify.py
```

Latest local check: **14 September 2026**, Python 3.14.3 on macOS.
All **25 tests passed**: 6 quality-gate tests and 19 CatalogCue tests.
The verifier also passed fixture/exit-code checks, the monitoring walkthrough
and 158 relative document links. The quality-gate fixture has two passing
records and one deliberate failing record.
Monitoring tests mock HTTP and notifications; these checks send no real alerts.

The verifier runs both suites, checks the quality-gate fixture and malformed
input exit codes, compares the six-step CatalogCue walkthrough with its
expected outcomes, and resolves relative document links. Link fragments and
external URLs are not checked. The Git whitespace check is also run before
committing an edition.

[GitHub Actions](../.github/workflows/test.yml) passed on Python 3.11, 3.12 and
3.13 on 13 September 2026. Each hosted job ran the same verifier: 25 unit tests,
example outcomes, CLI exit codes and relative documentation links.
[Inspect the successful publication run](https://github.com/jamestraimbler-lgtm/applied-ai-portfolio/actions/runs/34753343486).

[Repository privacy](repository-privacy.md) records the credential scan,
ongoing checks and the limitation concerning retained historical metadata.

## Where the journal's claims come from

| Claim | Source inspected | Reproducibility for a reviewer with access |
| --- | --- | --- |
| Python monitoring and response checks | Included code, examples and tests | Runnable here |
| Marketplace work in June | June 16–20 commits; source at `1ce28f9`, reinspected 14 September | Case study and selected access, intake and review excerpts; full source retained separately |
| Marketplace boundaries | Auth context, listing/admin routers, webhook, evaluator and gateway source | Source inspection; no deployed acceptance test |
| Veggie Kitchen completed episode | Retained episode-one render inspected with FFprobe; three frames reviewed | Included preview frame; full 117.259-second render retained for walkthrough |
| Veggie Kitchen workflow | Archived script, image, animation, voice, caption and assembly source; scene outputs | Case study; no current-provider rerun or publication verified |
| Prediction-market components | Retained Python module definitions | Source study; no canonical version or financial audit |
| MemeSniper progression | July commits and later README/research evidence | Historical case study; runtime data author-held |
| Robinhood stop decision | September 8 `docs/BUILD-STATUS.md` and retained campaign account | Historical summary; not rerun here |
| August monitoring/model work | Packaging/project-review history and current source files | Retrospective date anchors, not start dates |
| September reassessment | Retained September 12 review report | Historical review, not current market guidance |
| Portfolio creation | September 11 initial local commit `0ea9f50` and task record | Original local history retained privately; this repository starts with the reviewed portfolio |

This is a selected software history, not a complete computer inventory.
Folder names, installed apps and dependencies alone do not demonstrate skill.
Sensitive material and work with unresolved contribution or publication
ownership are excluded from public evidence.

The audit did not run private trading projects, contact billing services,
reconcile wallets, verify customers or test the full marketplace. It did not
rerun media generation or assess the complete video's audio and timing.
Source excerpts and retained artifacts support specific implementation claims;
they do not establish unaided coding ability or professional outcomes.
[Skills map](skills-and-next-steps.md).
