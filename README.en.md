[Nederlands](README.md) · [English](README.en.md)

# Daan Klein — practical projects with AI

I am a self-taught builder in the Netherlands, seeking my first professional
role. My projects span web applications, backend workflows, automation and
AI video production. I enjoy investigating an unfamiliar problem, connecting
the pieces it needs and turning an idea into something concrete.

This portfolio shows the breadth of that work and where each project stands.
I use AI tools extensively to build and learn; [how I work](docs/how-i-work.md)
explains my contribution and a practical way to assess it.

**Languages:** Dutch, English and conversational French.

## Start here

| You want to… | Read or try… |
| --- | --- |
| See how I connect a product's moving parts | [AI marketplace: accounts, submissions, review and integrations](projects/ai-marketplace/README.md) |
| See a creative workflow with a finished output | [Veggie Kitchen: a 117-second AI video episode](projects/veggie-kitchen/README.md) |
| Run a small example | [CatalogCue: confirmed changes and reliable notifications](projects/catalogcue/README.md) |
| Understand my background and strengths | [Profile](docs/application-profile.md) and [skills map](docs/skills-and-next-steps.md) |
| Follow the wider story | [Learning journal](journal/README.md) and [project endpoints](docs/project-status.md) |

## Featured project: AI marketplace

A marketplace needs more than a catalogue page. Sellers need accounts and
structured submissions; reviewers need context and a way to make decisions;
external events need to update the right records.

My TypeScript prototype brings those concerns together:

- Server-side session verification and user, seller and administrator access.
- Validated listing intake, with related records saved in one database transaction.
- Submission review, an escalation queue and recorded human decisions.
- Subscription-event handling and integration with external services.

These are useful foundations for internal tools and program administration:
registration, application review and keeping records in sync. That is a
transferable pattern, rather than a claim that I have already run a participant
program. The case study includes source excerpts and specific remaining work.

**Endpoint:** a substantial application prototype, with unfinished billing
and gateway paths. [Architecture, evidence and limits](projects/ai-marketplace/README.md).

## Breadth with concrete endpoints

| Project | What it demonstrates | Current endpoint |
| --- | --- | --- |
| [AI marketplace](projects/ai-marketplace/README.md) | Web application, permissions, structured intake, human review and service integration | Documented prototype; full application is not included here |
| [Veggie Kitchen](projects/veggie-kitchen/README.md) | Structured scripts, generated images, animation, voices, captions and video assembly | One finished episode retained; wider series pipeline archived and unfinished |
| [CatalogCue](projects/catalogcue/README.md) | Python, HTTP, persistent state, confirmation and delivery retries | Runnable offline sample; wider StoreWatch product unfinished |
| [LLM quality gate](demos/llm-quality-gate/README.md) | Explicit text and JSONL checks, CLI and tests | Completed small demo; does not establish factual correctness |
| [Decision systems](projects/decision-systems/README.md) | Data quality, research and lessons from negative results | Research case study; no proven profitable strategy |
| [Prediction-market automation](projects/prediction-market-automation/README.md) | API adapters, order lifecycle and reconciliation | Historical source study |

The [project register](docs/project-status.md) defines each endpoint. Some
work can be run directly here; larger projects are documented case studies.

## Run the included examples

From this directory, with Python 3.11 or newer:

```bash
python3 projects/catalogcue/demo.py
python3 scripts/verify.py
```

CatalogCue ignores a temporary price drop, confirms a repeated change and
retains a failed notification for retry. The demo uses the actual engine with
simulated pages and delivery outcomes; no API account is required.

The verifier runs **25 tests** across the two Python examples, checks demo
outcomes and CLI exit codes, and resolves local documentation links.
[Verification record and evidence boundaries](docs/evidence.md).

The introduction, profile, working approach, learning goals and Python demos
are available in Dutch and English. Detailed technical case studies are in
English. Repository access is arranged separately; a link alone does not
grant access to a private repository.
