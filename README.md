[Nederlands](README.md) · [English](README.en.md)

# Daan Klein — automatisering bouwen met AI

Ik ben een autodidactische developer in Nederland en zoek een juniorfunctie
in automatisering, toegepaste AI, softwaretesten of API-integratie. Ik werk
met Python en TypeScript, met veel hulp van AI-tools. Mijn volgende stap is
werken in een team, met code review, duidelijke doelen en echte gebruikers.

Hier staan twee kleine Python-voorbeelden die je zelf kunt uitvoeren, plus
een [logboek van mijn leertraject](journal/README.nl.md). De voorbeelden laten
zien hoe de software omgaat met onbetrouwbare invoer, fouten en herstel.

**Talen:** Nederlands, Engels en Frans op conversatieniveau.

## Begin hier

| Je wilt… | Bekijk… |
| --- | --- |
| In twee minuten weten wie ik ben | [Profiel en bijdrage](docs/application-profile.nl.md) |
| Een concreet resultaat zien | [CatalogCue: een valse prijsmelding voorkomen en bezorging opnieuw proberen](projects/catalogcue/README.nl.md) |
| Mijn niveau en leerdoelen inschatten | [Vaardigheden en volgende stappen](docs/skills-and-next-steps.nl.md) |
| Code beoordelen | [Monitoringcode](projects/catalogcue/storewatch.py), [tests](projects/catalogcue/test_storewatch.py) en [outputcontrole](demos/llm-quality-gate/quality_gate.py) |
| Begrijpen hoe ik AI gebruik | [Werkwijze en mijn aandeel](docs/how-i-work.nl.md) |

## Uitgelicht: CatalogCue

Een productpagina laat één keer een lagere prijs zien en daarna weer de oude
prijs. Meteen een melding sturen zou ruis veroorzaken. De monitor wacht op
twee overeenkomende waarnemingen. Mislukt het versturen, dan bewaart hij de
melding om het opnieuw te proberen.

| Situatie in de demo | Resultaat |
| --- | --- |
| Prijs 100 → 90 → 100 | Geen wijzigingsmelding |
| Prijs 90 wordt twee keer waargenomen | Eén bevestigde wijziging |
| Bezorging mislukt en herstelt | Melding blijft bewaard en wordt later verstuurd |

**Zelf uitvoeren:** vanuit deze map, met Python 3.11 of nieuwer:

```bash
python3 projects/catalogcue/demo.py
python3 scripts/verify.py
```

De demo gebruikt de echte monitoringcode met gesimuleerde pagina's en
bezorgresultaten. Je hebt geen API-account nodig. Het is een uitvoerbaar
voorbeeld; het bredere product is nog niet af. [Uitleg, code en beperkingen](projects/catalogcue/README.nl.md).

## Projecten en eindpunten

| Project | Wat je kunt bekijken | Huidige status |
| --- | --- | --- |
| [CatalogCue](projects/catalogcue/README.nl.md) | Python, HTTP, toestand bewaren, bevestigen en opnieuw proberen | Uitvoerbaar voorbeeld; breder product onaf |
| [LLM quality gate](demos/llm-quality-gate/README.nl.md) | Vaste controles op tekst en JSONL, CLI en tests | Kleine afgeronde demo; controleert geen feitelijke juistheid |
| [AI-marktplaats — Engelse casus](projects/ai-marketplace/README.md) | TypeScript, validatie, authenticatie, betalingen en MCP | Prototype beschreven; concrete integratiestappen ontbreken |
| [Beslissystemen — Engelse casus](projects/decision-systems/README.md) | Datakwaliteit, onderzoek en lessen uit negatieve resultaten | Onderzoek vastgelegd; geen bewezen winstgevende strategie |
| [Voorspellingsmarkten — Engelse casus](projects/prediction-market-automation/README.md) | API-adapters, orderstappen en reconciliatie | Historische bronstudie |

Het [projectregister (Engels)](docs/project-status.md) beschrijft precies waar
ieder project stopt. De [Nederlandse samenvatting van mijn leertraject](journal/README.nl.md)
verbindt de projecten met elkaar; het volledige logboek is in het Engels.

## Controleerbaar werk

De twee voorbeelden hebben samen **25 tests**: 19 voor monitoring en 6 voor
de quality gate. De verificatie controleert ook de demo-uitkomsten, exitcodes
en lokale documentatielinks. Netwerkverkeer en meldingen zijn gesimuleerd.

[Geslaagde GitHub-controles van 13 september 2026](https://github.com/jamestraimbler-lgtm/applied-ai-portfolio/actions/runs/34756299769)
op Python 3.11, 3.12 en 3.13. [Bewijs en grenzen (Engels)](docs/evidence.md).

AI heeft veel bijgedragen aan de code, tests en teksten. Mijn begrip kun je
beoordelen door samen één voorbeeld door te nemen en een kleine wijziging
te bespreken. [Meer over mijn werkwijze](docs/how-i-work.nl.md).

De introductie, het profiel, de leerdoelen en de twee demonstraties zijn in
het Nederlands en Engels beschikbaar. Broncode en uitgebreide technische
casussen blijven in het Engels. Toegang tot deze repository wordt apart
geregeld; een link geeft op zichzelf geen toegang tot een privérepository.
