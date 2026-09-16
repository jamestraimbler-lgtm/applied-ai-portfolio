# Brain — forecasting and research infrastructure

Brain is an archived, AI-assisted research project for collecting information,
recording forecasts and testing whether apparent signals survive comparison
with controls. It is a substantial personal research codebase, not a proven
forecasting service or profitable trading system.

## A short code tour

| Question | Source |
| --- | --- |
| How are forecasts and research requests handled? | [brain.py](source/brain.py), [brain_v2.py](source/brain_v2.py), [brain_search.py](source/brain_search.py) |
| How are observations measured and tracked? | [news_flag.py](source/news_flag.py), [measurer.py](source/measurer.py), [brain_status.py](source/brain_status.py) |
| How do I compare a hypothesis with a control? | [placebo.py](source/placebo.py), [validation.py](source/validation.py) |
| How do external data sources connect? | [Source adapters](source/sources), [Deribit](source/deribit.py), [Manifold](source/manifold.py), [Kalshi data](source/kalshi_fetch.py) |
| How were simulations explored? | [Paper book](source/paper_book.py), [market-maker simulation](source/mm_sim.py) |

The validation module contains minimum-sample and effect-size criteria,
permutation tests, bootstrap intervals and multiple-comparison correction.
These are implemented techniques to inspect; their presence alone does not
validate the research design, source coverage or a real-world prediction.

## Run the synthetic statistical walkthrough

From the portfolio root, in a Python environment with NumPy installed:

```bash
python3 -m pip install -r projects/brain/requirements-demo.txt
python3 projects/brain/source/validation.py
```

This uses generated observations to show noise, an injected signal and an
insufficient sample. It makes no API calls and does not load historical records.
The examples print their results; see the [verification record](../../docs/verification-2026-09-16.md)
for the outcomes actually observed.

## Scope of the source release

All 50 Python files from the archive's root and `sources` directory are included.
The original code contains overlapping research generations and assumptions
specific to its historical environment. This is a source snapshot for review,
not a polished installation of the entire research stack. Provider-backed
commands may require separate SDKs, credentials and compatible provider APIs.

Private logs, predictions, balances, machine scheduling and account files are
excluded. The hard-coded desktop alert path was replaced with `BRAIN_ALERT_FILE`
(default: a local text file). No live service or trading mode was changed.

What reflects my learning here is making hypotheses inspectable, measuring
missing evidence and preserving negative conclusions. No after-cost advantage,
calibrated forecasting accuracy or production reliability is claimed.

[Portfolio](../../README.md) · [Related research history](../decision-systems/README.md)
