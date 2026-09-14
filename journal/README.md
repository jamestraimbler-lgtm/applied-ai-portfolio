[Nederlandse samenvatting](README.nl.md) · [English](README.md)

# My AI and software journey

I have used AI tools to explore ideas across software, backend workflows,
automation and creative production. The common thread is learning the parts
an idea needs, connecting them and investigating what happens. Over time, I
paid more attention to useful milestones and what each result actually proves.

Written on 13 September and expanded on 14 September 2026, this is a
retrospective reconstructed from code,
commits, reports and conversations. It is not a diary written at the time.
Dates identify surviving evidence, not when I first learned a technology.
Projects overlapped. AI tools helped build the software and prepare this
journal; [how I work](../docs/how-i-work.md) explains that openly.

## Early automation: connecting information to action

Retained prediction-market bot copies contain market-data adapters, scanners,
a paper trader, order functions, trade records and fill-reconciliation logic.
They show how broad an automation project becomes beyond one API request.
There is no reliable start date in the inspected copies.

Fetching a price, submitting an order and confirming a fill are separate
responsibilities. The next step needs records that distinguish them. Source
files alone do not establish that the whole lifecycle worked reliably.

**Endpoint:** historical engineering context, with no public profit claim.
[Project note](../projects/prediction-market-automation/README.md).

## June 2026: a marketplace for AI tools

Retained commits from 16–20 June cover a marketplace for MCP servers, with
seller workflows, subscriptions, reviews and access control. The stack includes
Next.js, TypeScript, tRPC, Prisma and Zod.

One design choice keeps validation and access rules at the API boundary.
Another updates a review and its aggregate rating within a database transaction.
The source also contains Supabase session resolution, Stripe Checkout and
webhook handling, capability probing and access-key validation. A closer
backend review also found transactional listing intake, a submission-review
workflow, an administrator escalation queue and recorded human decisions.
Those are useful patterns for other systems that collect information and
route it to the right next action.

September's audit caught a documentation problem: the old README described
authentication and Checkout as unwired even though implementations existed.
The actual remaining steps are more specific: cancellation does not call
Stripe, the gateway does not forward MCP requests, and the evaluator is a
rules-based stub.

**Lesson:** finishing part of an integration does not finish the user journey.
Documentation should name the exact remaining step.

**Endpoint:** a documented prototype, without a deployed-service claim.
[Architecture and unfinished paths](../projects/ai-marketplace/README.md).

## An archived creative experiment: Veggie Kitchen

This project moved into a different domain: turning structured scene scripts
into an animated episode. It connects generated images, Kling animation,
ElevenLabs voices, Whisper caption timing and FFmpeg assembly. The retained
source also separates character and story context from individual scenes.

The archive contains a completed first episode: 117.259 seconds, vertical
1080 × 1920 video with audio, plus its intermediate scene assets. Episode two
remains partial. The archive was inspected on 14 September; this is an evidence
review date, not an established project start date.

**Lesson:** a creative workflow also benefits from explicit stages and saved
intermediate outputs. A finished export is a concrete milestone even when the
larger series or tool remains unfinished.

**Endpoint:** one completed episode, a preview and a documented archived
pipeline. No audience, advertising or commercial result is claimed.
[Workflow and preview](../projects/veggie-kitchen/README.md).

## July–September 2026: learning from unreliable results

MemeSniper grew through several versions. Retained legacy commits cover July;
later research documents cover August and September. The work brought together
incoming events, provider limits, selection, execution controls and accounting.

The hardest lesson was that improving the machinery did not establish a better
trading strategy. An attractive result could depend on an incomplete exit, a
provider error or one exceptional winner. A dataset could look usable until
its timestamps showed that information arrived in the wrong order.

Later research treated discovery, selection, execution and economics as
separate questions. Invalid or incomplete evidence was explicitly excluded
instead of silently repaired into a success.

This also exposed a habit I want to improve: refining an uncertain idea for
too long. A smaller question and an earlier stopping rule would have made the
effort easier to evaluate.

**Endpoint:** preserve the engineering lessons and negative research
conclusion. The portfolio does not present a profitable trading strategy.
[Decision-systems case study](../projects/decision-systems/README.md).

## By August 2026: a narrower problem with CatalogCue

StoreWatch, later presented as CatalogCue, explored product-page monitoring.
A retained August packaging record and the source establish work by that date;
the original start date is not established here.

Pages and networks are noisy. The engine requires repeated matching
observations before alerting, records confirmed failures and recoveries, and
retains failed notifications for retry. The included tests cover those cases.

The wider product remains unfinished. An engine and a sales offer do not
establish customer adoption. The behavior under controlled tests is the part
that can be shown clearly.

**Lesson:** a small workflow with understandable failure cases is easier for
someone else to review than a sprawling system with an uncertain outcome.

**Endpoint:** a runnable engineering sample. Finishing the product would need
a user's agreed pages, acceptance criteria and operational handover.
[Code and worked example](../projects/catalogcue/README.md).

## August 2026: trying a model API

The August project review recorded an OpenRouter sandbox. Its files contain a
minimal Node client and setup instructions. That establishes API exploration,
not a finished AI application or a measured model comparison.

**Lesson:** trying a model is useful learning. It deserves a small place in
the story without becoming a flagship project.

**Endpoint:** a small exploration recorded. A future application needs a user
problem and evaluation examples before model comparison becomes meaningful.

## September 7–12: deciding where research should stop

Robinhood Chain research recorded both provider limitations and modeled
economic outcomes. Its September 8 final material-flow campaign reported six
cohorts and 36 complete modeled exits, with negative treatment and control
results. Too few admission differences also left the intended comparison
inconclusive. Complete accounting made the stop decision clearer.

Follow-up research examined liquidations and alternative payment mechanisms.
A September 12 review of a proposed BTC strategy found mismatched rules,
incomplete costs and insufficient independent validation. These are historical
research findings, not current investment guidance.

**Lesson:** a plausible explanation and a polished backtest still need
consistent rules, realistic costs and evidence not used during tuning.

**Endpoint:** a research conclusion and unresolved feasibility questions.
There is no newly proven income system in this portfolio.
[Research boundaries](../projects/decision-systems/README.md).

## September 11–13: making the work reviewable

A separate portfolio repository was created on September 11 with two small
Python examples and case studies. On September 13, both suites were rerun:
6 quality-gate tests and 19 CatalogCue tests passed.

The monitoring sample now includes an offline walkthrough of a temporary price
drop, a confirmed change and notification retry. It uses the actual engine with
simulated external responses. A single verification command runs both suites,
checks the walkthrough's outcomes and validates local documentation links.

The LLM quality gate checks explicit terms, declared citation presence and
length constraints. It does not verify whether a source supports a claim or
judge semantic truth. Its value is a contract that can be read and tested.

This journal gives the larger projects context and an endpoint. It also
distinguishes technologies visible in an artifact from skills I still need
to demonstrate in a team.

## September 14: making the breadth visible

The portfolio now leads with the marketplace's connected backend and adds the
archived video workflow. This better represents the range of work: application
infrastructure, creative production, practical automation and research. Each
case keeps its own evidence and stopping point.

**Next stop:** contribute that breadth to a team, learn the context of its
work and own a useful first deliverable with feedback and a clear definition
of done. [Strengths and learning plan](../docs/skills-and-next-steps.md).
