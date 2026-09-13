# Strengths, exposure and next learning steps

This map describes project evidence, not a numerical rating of my ability.
The work was substantially AI-assisted. Explaining, changing and debugging
an artifact with a reviewer is a separate demonstration of my understanding.

## Strongest public evidence

| Area | Concrete evidence | Interview discussion |
| --- | --- | --- |
| Python and CLI tools | [Quality gate](../demos/llm-quality-gate/quality_gate.py): validation, JSONL and exit codes | Malformed input versus a valid record failing a rule |
| Testing failure cases | [Monitoring tests](../projects/catalogcue/test_storewatch.py) | Why an unstable page change should not alert |
| State and retries | [Monitoring engine](../projects/catalogcue/storewatch.py) | What if delivery succeeds but the process crashes before saving? |
| Evaluation limits | [Quality-gate documentation](../demos/llm-quality-gate/README.md) | An incorrect answer that still passes structural checks |
| Clear handoffs | [Project endpoints](project-status.md) and [evidence record](evidence.md) | The next implementable task without reopening the whole project |

The strongest pattern is work on integrations, state, failure visibility and
evaluation. “Expert” or “independent mastery” would exceed the reviewed evidence.

## Worked with in larger projects

| Technology or practice | Evidence level | Still to demonstrate |
| --- | --- | --- |
| TypeScript, React, Next.js, tRPC, Zod | Marketplace source inspected | Explain a request path and deliver a reviewed change |
| SQL, Prisma, PostgreSQL, transactions | Schema, migrations and transaction use | Operate migrations and recovery in a shared environment |
| Supabase and Stripe | Integration code exists; incomplete paths remain | A complete sandbox signup, billing and cancellation lifecycle |
| MCP and JSON-RPC | Probe, test-server and gateway work | Forward requests and test authorization failures |
| REST APIs and event data | Monitoring sample and research source | Support an integration with agreed service expectations |
| Local scheduling and diagnostics | Original monitoring and research scripts | Deployment, rollback and incident response with a team |
| Git and GitHub Actions | Local commits and checked-in Python workflow | Reviewed pull requests and a successful hosted workflow |
| Model APIs and AI-assisted development | Minimal OpenRouter client and project work | A useful model feature evaluated on held-out examples |

## Not established here

This audit did not establish depth in Docker, cloud infrastructure,
infrastructure as code, vector databases, RAG, model training, fine-tuning or
large-scale distributed systems. It also did not establish sustained customer
adoption or professional team delivery. Insufficient evidence does not mean
I have never encountered a topic.

## A small learning sequence

| Next step | Definition of done |
| --- | --- |
| Explain and change an existing example | Walk through the monitoring state machine, make an agreed change and justify its test |
| Deliver one small integration | Agree acceptance criteria, handle malformed input and an outage, obtain user acceptance |
| Practice team delivery | One issue, branch, reviewed pull request, passing CI and clear handoff |
| Learn deployment and recovery | Deploy that same service, document configuration and demonstrate rollback |
| Add AI where it helps | Compare a model feature with a simple baseline on examples held aside before tuning |

These are proposed goals, not completed work or five new projects. The first
task should be chosen with the team.
