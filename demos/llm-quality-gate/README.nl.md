[Nederlands](README.nl.md) · [English](README.md)

# LLM quality gate — vaste voorwaarden controleren

Een kleine Python-CLI die gestructureerde antwoorden controleert op
vooraf ingestelde regels: verplichte woorden of tekstfragmenten,
verboden claims, een aanwezige bronverwijzingslijst en maximale lengte.

De tool gebruikt vaste regels en roept geen model-API aan. Hij kan helpen
om herhaalbare voorwaarden te toetsen naast inhoudelijke beoordeling.

## Voorbeeld uitvoeren

Vanuit de hoofdmap van de repository, met Python 3.11 of nieuwer:

```bash
python3 demos/llm-quality-gate/quality_gate.py demos/llm-quality-gate/examples/responses.jsonl --report-only
```

[Het invoerbestand](examples/responses.jsonl) bevat één JSON-object per regel.
Per geval verschijnt één JSON-resultaat. Twee voorbeeldgevallen slagen en
één faalt bewust.

| Gebruik | Uitkomst |
| --- | --- |
| Met `--report-only` en geldige invoer | Rapport tonen; exitcode 0 |
| Zonder `--report-only`, minstens één regel faalt | Exitcode 1 |
| Ongeldige JSON-invoer | Exitcode 2 |

Zo kan een automatisch proces onderscheid maken tussen rapporteren, een
afgekeurd resultaat en ongeldige invoer.

## Code en tests

[quality_gate.py](quality_gate.py) bevat de controles. De [Engelse uitleg](README.md)
beschrijft het invoerformaat.

```bash
python3 -m unittest discover -s demos/llm-quality-gate -p 'test_*.py'
python3 scripts/verify.py
```

## Wat dit resultaat betekent

Verplichte tekst wordt gecontroleerd met fragmentvergelijking zonder
onderscheid tussen hoofdletters en kleine letters. Bij bronverwijzingen
controleert de tool alleen of de lijst niet leeg is. Hij haalt geen bronnen
op en controleert niet of ze een antwoord ondersteunen.

De score is het aandeel geslaagde controles, geen kans dat het antwoord
juist is. Een feitelijk onjuist antwoord kan dus slagen.

## Eindpunt

**Kleine afgeronde demo met vaste regels.** Op 13 september 2026 slaagden
alle zes tests. Evaluatie van echte modeluitvoer op inhoud en feitelijke
juistheid valt buiten dit voorbeeld.

[Projectregister (Engels)](../../docs/project-status.md) ·
[Mijn werkwijze](../../docs/how-i-work.nl.md) · [Startpagina](../../README.md)
