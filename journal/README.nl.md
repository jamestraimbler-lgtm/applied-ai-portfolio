[Nederlandse samenvatting](README.nl.md) · [Full English journal](README.md)

# Mijn leertraject met AI en software

Dit is een Nederlandse samenvatting van het [volledige Engelstalige logboek](README.md).
De terugblik is op 13 september 2026 samengesteld uit code, commits,
rapporten en gesprekken; deze samenvatting is op 14 september toegevoegd.
Het is geen dagboek dat tijdens de projecten is bijgehouden. AI hielp bij
de software en de teksten. Projecten liepen deels tegelijk.

De projecten lopen uiteen van backendprocessen en automatisering tot
creatieve productie. De rode draad is nieuwe onderdelen leren, ze verbinden
en onderzoeken wat er gebeurt. Gaandeweg werden bruikbare mijlpalen en wat
een resultaat werkelijk bewijst steeds belangrijker.

## Vroege automatisering

De bewaarde code voor voorspellingsmarkten bevat datakoppelingen, scanners,
gesimuleerde handel, orderfuncties en logica voor het controleren van
uitvoering. Een betrouwbare begindatum ontbreekt. De les is dat een prijs
ophalen, een order versturen en de uitvoering bevestigen verschillende
stappen zijn.

**Eindpunt:** historische technische context; geen winstclaim.

## Juni 2026: de marktplaats achter AImazon

Ik noem het productidee AImazon: een plek waar particulieren en bedrijven
AI-agents kunnen vinden en makers ze kunnen aanbieden. Het prototype verkent
het platform erachter; het beoogde product is breder dan wat nu is uitgewerkt.

Bewaarde commits van 16–20 juni beschrijven een marktplaats voor MCP-servers.
Ik werkte met AI aan onder meer TypeScript, Next.js, tRPC, Prisma, Zod,
toegangscontrole en betalingen. De broncode bevat bijvoorbeeld validatie aan
de API-grens en een transactie voor een review en de gemiddelde beoordeling.
Ook de invoer van gerelateerde gegevens, een beoordelingsproces, een
escalatiewachtrij en het vastleggen van menselijke beslissingen zijn in de
backend uitgewerkt.

Een latere controle liet zien dat de documentatie te algemeen was over
ontbrekende integraties. Authenticatie en Checkout bestonden al, maar
annulering, MCP-verzoeken doorsturen en evaluatie hadden nog concrete gaten.

**Eindpunt:** een beschreven prototype. De les is om de ontbrekende stap
precies te benoemen.

## Een gearchiveerd creatief experiment: Veggie Kitchen

Bij dit project ging ik een ander gebied in: gestructureerde scènes omzetten
in een geanimeerde aflevering. Het verbindt gegenereerde beelden, Kling-animatie,
ElevenLabs-stemmen, Whisper voor timing en FFmpeg voor montage en ondertiteling.

In het archief staat één afgeronde aflevering van 117 seconden in verticaal
1080 × 1920-formaat met geluid en de bijbehorende tussenbestanden. Aflevering
twee is gedeeltelijk gemaakt. Het archief is op 14 september onderzocht; een
betrouwbare begindatum is hiermee niet vastgesteld.

**Eindpunt:** één afgeronde aflevering met een [voorbeeldbeeld en casus](../projects/veggie-kitchen/README.md).
Het bredere proces is gearchiveerd. Publicatie, kijkcijfers en commerciële
resultaten zijn niet gecontroleerd. Ook creatief werk heeft baat bij duidelijke
stappen en bewaarde tussenresultaten.

## Juli–september: leren van onbetrouwbare resultaten

Onderzoek aan beslissystemen bracht eventdata, providerlimieten, selectie,
uitvoering en administratie samen. Betere software leverde niet vanzelf
een betere handelsstrategie op. Onvolledige afsluitingen, timingfouten of
een uitzonderlijke winnaar konden resultaten vertekenen.

Ik bleef soms te lang aan een onzeker idee schaven. Kleinere onderzoeksvragen
en eerdere stopcriteria zouden het werk beter afbakenen.

**Eindpunt:** technische lessen en negatieve onderzoeksresultaten bewaren;
geen bewezen winstgevende strategie.

## Uiterlijk augustus: een kleiner probleem met CatalogCue

StoreWatch, hier gepresenteerd als CatalogCue, onderzocht productpagina's.
Tijdelijke afwijkingen en mislukte meldingen maakten betrouwbaarheid
belangrijk. Het voorbeeld bevestigt wijzigingen, bewaart toestand en
probeert mislukte bezorging opnieuw.

**Eindpunt:** een [uitvoerbaar monitoringvoorbeeld](../projects/catalogcue/README.nl.md).
Het bredere product heeft nog gebruikersacceptatie en operationele overdracht
nodig. De offline demo is geschikt om tijdens een gesprek uit te voeren.

## Augustus: een model-API proberen

Een kleine OpenRouter-client laat zien dat ik een model-API heb verkend.
Dat is ervaring met een koppeling, maar nog geen complete AI-toepassing of
onderbouwde modelvergelijking.

**Eindpunt:** een beperkte verkenning vastgelegd.

## September: onderzoek afronden en bewijs ordenen

Robinhood-onderzoek legde providerproblemen en negatieve gemodelleerde
resultaten vast. Vervolgonderzoek naar andere mechanismen liet nog
haalbaarheidsvragen open. Er volgde geen bewezen inkomstenmodel.

Voor dit portfolio zijn twee kleine Python-voorbeelden en casussen
samengebracht. Op 13 september slaagden 19 monitoringtests en 6 tests voor
de quality gate. Die laatste controleert vaste voorwaarden in tekst en
JSONL; hij beoordeelt geen feitelijke juistheid.

Op 14 september zijn de backend van de marktplaats en de creatieve
videoproductie duidelijker in het portfolio opgenomen. Zo wordt de breedte
zichtbaar, terwijl ieder project zijn eigen bewijs en eindpunt behoudt.

**Volgende stap:** die breedte inzetten in een team, de context leren en een
eerste bruikbaar resultaat opleveren met feedback en een duidelijk eindpunt.

[Mijn profiel](../docs/application-profile.nl.md) · [Leerdoelen](../docs/skills-and-next-steps.nl.md) · [Werkwijze](../docs/how-i-work.nl.md) · [Startpagina](../README.md)
