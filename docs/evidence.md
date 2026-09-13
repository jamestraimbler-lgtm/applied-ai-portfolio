# Evidence and verification — 13 September 2026

## Reproduce the public checks

Run from the repository root:

```bash
python3 scripts/verify.py
```

Local environment: Python 3.14.3 on macOS. Results: 6 quality-gate tests and 19
CatalogCue tests passed. The report has two passes and one deliberate failure.
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

| Claim | Source inspected | Public reproducibility |
| --- | --- | --- |
| Python monitoring and response checks | Included code, examples and tests | Runnable here |
| Marketplace work in June | June 16–20 commits; source at `1ce28f9` | Case study and excerpt; full source author-held |
| Marketplace boundaries | Auth context, routers, webhook, evaluator and gateway source | Inspection; no deployed acceptance test |
| Prediction-market components | Retained Python module definitions | Source study; no canonical version or financial audit |
| MemeSniper progression | July commits and later README/research evidence | Historical case study; runtime data author-held |
| Robinhood stop decision | September 8 `docs/BUILD-STATUS.md` and retained campaign account | Historical summary; not rerun here |
| August monitoring/model work | Packaging/project-review history and current source files | Retrospective date anchors, not start dates |
| September reassessment | Retained September 12 review report | Historical review, not current market guidance |
| Portfolio creation | September 11 initial local commit `0ea9f50` and task record | Original local history retained privately; public history starts with the reviewed portfolio |

This is a selected software history, not a complete computer inventory.
Folder names, installed apps and dependencies alone do not demonstrate skill.
Sensitive material and work with unresolved contribution or publication
ownership are excluded from public evidence.

The audit did not run private trading projects, contact billing services,
reconcile wallets, verify customers or test the full marketplace. It did not
establish unaided coding ability. [Skills map](skills-and-next-steps.md).
