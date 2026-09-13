# Decision systems — learning to trust a result

These personal, substantially AI-assisted experiments asked whether fast-moving
market data could support useful automated decisions. They include several
MemeSniper versions and separate Robinhood Chain research.

## The problem

A system can discover candidates and produce attractive numbers while failing
to measure its objective. A price peak is not a fill. A missing sell quote
does not prove a total loss. Information collected after a decision cannot
honestly predict its outcome.

The work separated four questions:

1. **Discovery:** was the opportunity visible at the relevant time?
2. **Selection:** did the rule choose usefully from that population?
3. **Execution:** could an authorized action complete at the required size?
4. **Economics:** were entry, exit, costs and inventory accounted for?

## What the versions contributed

| Track | Engineering lesson | Endpoint |
| --- | --- | --- |
| MemeSniper v1 | Provider limits, durable intents and reconciliation | Legacy implementation history |
| MemeSniper v2 | Immutable evidence, exact identifiers, causal timing and completeness | Research/data-quality case study |
| MemeSniper v3 | Prospective selection, paper diagnostics and execution authority | Research with no proven edge |
| Robinhood Chain | Capability checks, shared anchors, controls and fixed cohorts | Material-flow hypothesis stopped after its campaign |

## A result that justified stopping

The retained September 8 Robinhood campaign report records six cohorts, 144
candidates and 36 complete modeled exits. Treatment and control were negative
after estimated gas. Only two admission disagreements were recorded, below
the required six, leaving the comparative hypothesis inconclusive.

The recorded verdict was `INCONCLUSIVE_STOP`: an underpowered comparison and
poor measured economics. Those modeled amounts are not funded-wallet losses.
The report also kept incomplete cost coverage explicit.

These are author-held historical report findings, inspected for this writeup.
The datasets are not published or rerun here. They explain the recorded stop,
not an independently reproducible public backtest.

## What remains useful

Timestamped records, exact identities, controls, diagnostics and reconciliation
are useful beyond trading. More filters or better machinery do not establish
a better decision rule. Stop criteria belong at an experiment's start.

Follow-up liquidation, carry and BTC research identified mechanisms and gaps.
It did not establish a profitable replacement.

## End of track

**Research with an honest negative conclusion.** This portfolio establishes no
profitable automated trading strategy. Trading source, wallets and operational
ledgers are not included. This document does not report current process status
or change a trading mode.

[Journal](../../journal/README.md) · [Project register](../../docs/project-status.md)
