[Nederlands](README.nl.md) · [English](README.md)

# Daan Klein — praktische projecten met AI

Ik ben een autodidactische bouwer in Nederland en zoek mijn eerste
professionele functie. Mijn projecten omvatten webapplicaties,
backendprocessen, automatisering en AI-videoproductie. Ik vind het leuk om
een onbekend probleem uit te zoeken, de benodigde onderdelen te verbinden
en een idee concreet te maken.

Dit portfolio laat de breedte van dat werk zien en geeft ieder project een
duidelijk eindpunt. Ik gebruik AI-tools intensief om te bouwen en te leren;
[mijn werkwijze](docs/how-i-work.nl.md) beschrijft mijn bijdrage en hoe je die
praktisch kunt beoordelen.

**Talen:** Nederlands, Engels en Frans op conversatieniveau.

**Contact:** [daan@superposition.life](mailto:daan@superposition.life)

## Begin hier

| Je wilt… | Bekijk… |
| --- | --- |
| Zien hoe ik de onderdelen van een product verbind | [AImazon: accounts, inzendingen, beoordeling en koppelingen](projects/ai-marketplace/README.md) |
| Een creatief proces met een afgerond resultaat zien | [Veggie Kitchen: een AI-videoaflevering van 117 seconden](projects/veggie-kitchen/README.md) |
| Zelf een klein voorbeeld uitvoeren | [CatalogCue: bevestigde wijzigingen en betrouwbare meldingen](projects/catalogcue/README.nl.md) |
| Mijn achtergrond en sterke punten begrijpen | [Profiel](docs/application-profile.nl.md) en [vaardigheden](docs/skills-and-next-steps.nl.md) |
| Het bredere verhaal volgen | [Leertraject](journal/README.nl.md) en [projecteindpunten](docs/project-status.md) |

## Uitgelicht: AImazon

AImazon is mijn concept voor een marktplaats waar particulieren en bedrijven
AI-agents kunnen vinden en makers hun agents kunnen aanbieden. Ik zie het als
een "Amazon voor AI". Het prototype verkent het platform achter dat idee,
met onder meer vermeldingen voor AI-tools en MCP-servers.

Daar is meer voor nodig dan een cataloguspagina. Aanbieders hebben
accounts en gestructureerde inzendingen nodig. Beoordelaars moeten informatie
kunnen bekijken en beslissingen vastleggen. Externe gebeurtenissen moeten de
juiste gegevens bijwerken.

Mijn TypeScript-prototype brengt die onderdelen samen:

- Sessiecontrole op de server en toegang voor gebruikers, aanbieders en beheerders.
- Gevalideerde invoer, met gerelateerde gegevens in één databasetransactie.
- Beoordeling van inzendingen, een wachtrij voor escalaties en vastgelegde menselijke beslissingen.
- Verwerking van abonnementsgebeurtenissen en koppelingen met externe diensten.

Bij het bouwen van dit prototype heb ik gebruikersprocessen, databasegegevens,
toegangsrechten en externe diensten met elkaar verbonden. Die bouwstenen zijn
ook bruikbaar voor andere webproducten, bedrijfsautomatisering en interne
hulpmiddelen. De [applicatiebroncode](projects/ai-marketplace/source/README.md)
is opgenomen; de casus benoemt wat nog moet gebeuren.

**Eindpunt:** een uitgebreid applicatieprototype, met onaf werk aan facturatie
en de gateway. [Architectuur, bewijs en beperkingen (Engels)](projects/ai-marketplace/README.md).

## Breedte met concrete eindpunten

| Project | Wat het laat zien | Huidig eindpunt |
| --- | --- | --- |
| [AImazon](projects/ai-marketplace/README.md) | Webapplicatie, toegangsrechten, invoer, menselijke beoordeling en koppelingen | Applicatiebroncode opgenomen; prototype, typecheck en build geslaagd |
| [Brain](projects/brain/README.md) | Onderzoek, voorspellingen, databronnen en statistische controles | 50 Python-bestanden; synthetische demonstratie gecontroleerd |
| [Mac Agent](projects/mac-agent/README.md) | SQLite-geheugen, projecttaken en dagelijkse rapporten | Vier bronmodules en een offline geheugendemonstratie |
| [Veggie Kitchen](projects/veggie-kitchen/README.md) | Gestructureerde scripts, beelden, animatie, stemmen, ondertiteling en montage | Eén afgeronde aflevering bewaard; breder serieproces gearchiveerd en onaf |
| [CatalogCue](projects/catalogcue/README.nl.md) | Python, HTTP, toestand bewaren, bevestigen en opnieuw versturen | Uitvoerbaar offline voorbeeld; het bredere StoreWatch-product is onaf |
| [LLM quality gate](demos/llm-quality-gate/README.nl.md) | Vaste controles op tekst en JSONL, CLI en tests | Kleine afgeronde demo; controleert geen feitelijke juistheid |
| [Beslissystemen](projects/decision-systems/README.md) | Datakwaliteit, onderzoek en lessen uit negatieve resultaten | Onderzoek vastgelegd; geen bewezen winstgevende strategie |
| [Voorspellingsmarkten](projects/prediction-market-automation/README.md) | API-adapters, orderstappen en reconciliatie | Historische bronstudie |

Het [projectregister (Engels)](docs/project-status.md) beschrijft ieder eindpunt.
Sommige voorbeelden kun je hier uitvoeren; grotere projecten zijn uitgewerkt
als casus.

## De voorbeelden uitvoeren

Vanuit deze map, met Python 3.11 of nieuwer:

```bash
python3 projects/catalogcue/demo.py
python3 scripts/verify.py
```

CatalogCue negeert een tijdelijke prijsdaling, bevestigt een herhaalde
wijziging en bewaart een mislukte melding voor een nieuwe poging. De demo
gebruikt de echte monitoringcode met gesimuleerde pagina's en bezorgresultaten.
Je hebt geen API-account nodig.

De verificatie voert **25 tests** uit voor de twee Python-voorbeelden en
controleert demo-uitkomsten, exitcodes en lokale documentatielinks.
[Verificatie en grenzen van het bewijs (Engels)](docs/evidence.md).

De introductie, het profiel, de werkwijze, leerdoelen en Python-demo's zijn
beschikbaar in het Nederlands en Engels. Uitgebreide technische casussen zijn
in het Engels.
