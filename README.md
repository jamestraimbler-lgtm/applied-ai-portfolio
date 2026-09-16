# Daan Klein — software, automation and applied AI

Self-taught builder in Delft, Netherlands, seeking my first professional role.
I build with Python, TypeScript and substantial AI assistance: web applications,
API integrations, research tools and creative workflows. I take responsibility
for the project direction, investigate failures and check what the result
actually does. [How I work](docs/how-i-work.md).

**Open to:** junior backend, integration, automation and technical generalist roles.
**Languages:** Dutch and English; conversational French.
**Contact:** [daan@superposition.life](mailto:daan@superposition.life) ·
[LinkedIn](https://www.linkedin.com/in/daan-klein-1b20a5437) ·
[Background](docs/application-profile.md) · [Nederlands](README.nl.md)

## Projects and the code behind them

| Project | What I built | Inspect or run | Status |
| --- | --- | --- | --- |
| **[AImazon](projects/ai-marketplace/README.md)** | Marketplace for discovering and listing AI agents: accounts, seller workflows, database transactions, review queues and billing integration | [Application source](projects/ai-marketplace/source), [API routers](projects/ai-marketplace/source/src/server/api/routers), [data model](projects/ai-marketplace/source/prisma/schema.prisma) | Substantial prototype; typechecked. Billing and gateway work remain |
| **[Brain](projects/brain/README.md)** | Forecasting research tooling, source adapters, recorded hypotheses, measurement and statistical controls | [50 Python source files](projects/brain/source), [synthetic validation](projects/brain/source/validation.py) | Archived research; offline statistical walkthrough verified |
| **[CatalogCue](projects/catalogcue/README.md)** | Website-change confirmation, persistent state and notification retries | [Engine](projects/catalogcue/storewatch.py), [offline demo](projects/catalogcue/demo.py), [19 tests](projects/catalogcue/test_storewatch.py) | Runnable sample from unfinished StoreWatch work |
| **[Mac Agent](projects/mac-agent/README.md)** | SQLite memory, project tracking, process/log inspection and daily briefing generation | [Four source modules](projects/mac-agent/source), [offline memory demo](projects/mac-agent/demo.py) | Archived tooling; memory walkthrough verified |
| **[Veggie Kitchen](projects/veggie-kitchen/README.md)** | Scripts, images, animation, voices, captions and assembly for a 117-second video | [Pipeline source](projects/veggie-kitchen/source), [preview](projects/veggie-kitchen/media/episode-1-preview.png) | One finished episode; wider pipeline archived |
| **[LLM quality gate](demos/llm-quality-gate/README.md)** | Explicit checks for text and JSONL outputs | [Code and six tests](demos/llm-quality-gate) | Small completed learning demo |

For a quick engineering review, start with AImazon's API and data model, then
run CatalogCue. Brain shows a larger research track; Veggie Kitchen shows a
different kind of workflow and a completed creative artifact.

## Run an example in a minute

Clone this repository, then from its root with Python 3.11 or newer:

```bash
python3 projects/catalogcue/demo.py
python3 projects/mac-agent/demo.py
python3 scripts/verify.py
```

The first two demonstrations are offline and need no credentials. The verifier
checks the existing 25 Python tests, demo outcomes, archived Python syntax and
local documentation links. Brain's NumPy demonstration and AImazon's TypeScript
checks have separate setup instructions in their project pages.

## Evidence, scope and learning

These are personal projects built with AI assistance. A source snapshot is not
a deployed product, and a passing typecheck is not an end-to-end test.
Each project page states what exists, how to inspect it and what remains.
[Current verification](docs/verification-2026-09-16.md) records the checks performed.

[Project register](docs/project-status.md) · [Learning journal](journal/README.md) ·
[Skills and next steps](docs/skills-and-next-steps.md) ·
[Source publication notes](docs/source-publication.md)

Earlier [decision-system research](projects/decision-systems/README.md) and
[prediction-market automation](projects/prediction-market-automation/README.md)
remain documented as engineering history. No profitable strategy is claimed.
