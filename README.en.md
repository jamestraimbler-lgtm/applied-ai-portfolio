[Nederlands](README.md) · [English](README.en.md)

# Daan Klein — building automation with AI

I am a self-taught developer in the Netherlands, looking for a junior role
in automation, applied AI, software testing or API integration. I work with
Python and TypeScript, with substantial help from AI tools. My next step is
working in a team with code review, clear goals and real users.

This repository contains two small Python examples you can run, alongside
a [journal of my learning](journal/README.md). The examples demonstrate how
the software handles unreliable inputs, failures and recovery.

**Languages:** Dutch, English and conversational French.

## Start here

| You want to… | Read or try… |
| --- | --- |
| Understand my background in two minutes | [Profile and contribution](docs/application-profile.md) |
| See a concrete result | [CatalogCue: avoid a false price alert and retry failed delivery](projects/catalogcue/README.md) |
| Assess my level and learning goals | [Skills and next steps](docs/skills-and-next-steps.md) |
| Review code | [Monitoring source](projects/catalogcue/storewatch.py), [tests](projects/catalogcue/test_storewatch.py) and [output validation](demos/llm-quality-gate/quality_gate.py) |
| Understand my use of AI | [How I work and my contribution](docs/how-i-work.md) |

## Featured example: CatalogCue

A product page shows a lower price once, then returns to the previous price.
Sending an immediate notification would create noise. The monitor waits for
two matching observations. If delivery fails, it retains the notification
for another attempt.

| Scenario in the demo | Result |
| --- | --- |
| Price 100 → 90 → 100 | No change notification |
| Price 90 observed twice | One confirmed change |
| Delivery fails and recovers | Notification is retained and delivered later |

**Run it:** from this directory, with Python 3.11 or newer:

```bash
python3 projects/catalogcue/demo.py
python3 scripts/verify.py
```

The demo uses the actual monitoring code with simulated pages and delivery
outcomes. No API account is needed. It is a runnable sample; the wider
product is unfinished. [Explanation, code and limits](projects/catalogcue/README.md).

## Projects and endpoints

| Project | What you can inspect | Current status |
| --- | --- | --- |
| [CatalogCue](projects/catalogcue/README.md) | Python, HTTP, persistent state, confirmation and retries | Runnable sample; wider product unfinished |
| [LLM quality gate](demos/llm-quality-gate/README.md) | Explicit text and JSONL checks, CLI and tests | Completed small demo; does not establish factual correctness |
| [AI marketplace](projects/ai-marketplace/README.md) | TypeScript, validation, authentication, billing and MCP | Documented prototype with specific integration gaps |
| [Decision systems](projects/decision-systems/README.md) | Data quality, research and lessons from negative results | Research case study; no proven profitable strategy |
| [Prediction-market automation](projects/prediction-market-automation/README.md) | API adapters, order lifecycle and reconciliation | Historical source study |

The [project register](docs/project-status.md) defines where each project
stops. The [journal](journal/README.md) connects them; a [Dutch summary](journal/README.nl.md)
is also available.

## Work you can verify

The two examples have **25 tests**: 19 for monitoring and 6 for the quality
gate. Verification also checks demo outcomes, exit codes and local
documentation links. Network calls and notifications are simulated.

[Successful GitHub checks from 13 September 2026](https://github.com/jamestraimbler-lgtm/applied-ai-portfolio/actions/runs/34756299769)
on Python 3.11, 3.12 and 3.13. [Evidence and limits](docs/evidence.md).

AI contributed substantially to the code, tests and documentation. A useful
way to assess my understanding is to walk through an example together and
discuss a small change. [More about how I work](docs/how-i-work.md).

The introduction, profile, learning goals and two demonstrations are
available in Dutch and English. Source code and detailed technical case
studies remain in English. Repository access is arranged separately;
a link alone does not grant access to a private repository.
