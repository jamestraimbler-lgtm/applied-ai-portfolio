[Nederlands](README.nl.md) · [English](README.md)

# CatalogCue — productpagina's controleren

Een Python-voorbeeld dat wijzigingen in productpagina's bevestigt en
mislukte meldingen bewaart voor een nieuwe poging. Het helpt onderzoeken
hoe je voorkomt dat tijdelijke afwijkingen tot onnodige meldingen leiden.

Dit portfolio bevat een opgeschoonde kopie van de monitoringcode.
Persoonlijke configuratie, runtimegegevens, meldingkanalen en
deploymentbestanden zijn niet opgenomen.

## Bekijk het gedrag

Voer dit uit vanuit de hoofdmap van de repository, met Python 3.11 of nieuwer:

```bash
python3 projects/catalogcue/demo.py
```

De demo gebruikt dezelfde `storewatch.run` als de monitor, met
gesimuleerde HTML-pagina's en bezorgresultaten. Toestand wordt in een tijdelijke
map opgeslagen. Een API-account of echte meldingendienst is niet nodig.

Een prijs begint op 100. Eén meting geeft 90, de volgende weer 100.
Die tijdelijke afwijking veroorzaakt geen melding. Pas na twee
overeenkomende metingen van 90 wordt de wijziging bevestigd. Als bezorging
mislukt, blijft de melding bewaard.

| Stap | Gemeten prijs | Bevestigde wijzigingen tot nu toe | Wachtende meldingen |
| --- | --- | --- | --- |
| Beginsituatie | 100 | 0 | 0 |
| Tijdelijke daling | 90 | 0 | 0 |
| Prijs herstelt | 100 | 0 | 0 |
| Eerste lagere meting | 90 | 0 | 0 |
| Bevestigd; bezorging mislukt | 90 | 1 | 1 |
| Bezorging herstelt | 90 | 1 | 0 |

## Waar zitten de keuzes in de code?

In [storewatch.py](storewatch.py):

- `evaluate_target` behandelt het bevestigen van waarnemingen.
- `queue_notification` bewaart de gebeurtenis.
- `flush_notifications` handelt bezorging en mislukte pogingen af.

[De tests](test_storewatch.py) behandelen tijdelijke afwijkingen, bevestigde
wijzigingen, fouten, herstel en het bewaren van toestand bij een dry run.
De code bevat ook HTTP-herhaalpogingen met oplopende wachttijden, extractie
van prijs en voorraad en filtering van veranderlijke pagina-inhoud.

## Zelf controleren

Vanuit de hoofdmap:

```bash
python3 -m unittest discover -s projects/catalogcue -p 'test_*.py'
python3 scripts/verify.py
```

De tweede opdracht controleert beide voorbeelden in het portfolio en vergelijkt
deze demo met de [verwachte JSONL-uitkomsten](demo-expected.jsonl). De gesimuleerde
bezorgfout geeft in stap vijf een foutcode van de monitor; de volledige demo
eindigt succesvol nadat bezorging herstelt.

## Eindpunt en beperkingen

**Uitvoerbaar voorbeeld; het bredere product is onaf.** Op 13 september 2026
slaagden alle 19 tests met gesimuleerde netwerkoproepen en meldingen.
Deze resultaten beschrijven gecontroleerd gedrag.

Een crash nadat verzenden is gelukt maar vóór het opslaan kan een dubbele
melding veroorzaken. Prijs- en voorraadextractie moeten voor echte
doelpagina's afzonderlijk worden gecontroleerd. Een hosted dienst en
langdurig klantgebruik zijn niet aangetoond.

De [Engelse technische toelichting](README.md) bevat meer informatie over
voorbeeldconfiguratie. [Projectregister (Engels)](../../docs/project-status.md) ·
[Mijn werkwijze](../../docs/how-i-work.nl.md) · [Startpagina](../../README.md)
