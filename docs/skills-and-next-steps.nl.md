[Nederlands](skills-and-next-steps.nl.md) · [English](skills-and-next-steps.md)

# Vaardigheden, ervaring en volgende stappen

Dit overzicht koppelt vaardigheden aan werk dat je kunt bekijken.
De software is met veel AI-hulp gemaakt. Mijn eigen begrip kan ik laten
zien door een voorbeeld uit te leggen, aan te passen en fouten te onderzoeken.

## Sterkste concrete voorbeelden

| Onderwerp | Werk dat je kunt bekijken | Bespreekbaar in een gesprek |
| --- | --- | --- |
| Python en CLI-tools | [Quality gate](../demos/llm-quality-gate/quality_gate.py): JSONL, controles en exitcodes | Ongeldige invoer versus geldige invoer die niet aan een regel voldoet |
| Fouten testen | [Monitoringtests](../projects/catalogcue/test_storewatch.py) | Waarom een tijdelijke prijswijziging geen melding moet veroorzaken |
| Toestand en herhaalde pogingen | [Monitoringcode](../projects/catalogcue/storewatch.py) | Wat als verzenden lukt, maar het proces crasht vóór het opslaan? |
| Grenzen van evaluatie | [Quality-gate-uitleg](../demos/llm-quality-gate/README.nl.md) | Een onjuist antwoord kan toch aan de vaste regels voldoen |
| Overdracht | [Projectregister (Engels)](project-status.md) en [bewijs (Engels)](evidence.md) | Een duidelijke volgende taak formuleren |

De duidelijkste lijn in mijn projecten is het koppelen van systemen,
fouten zichtbaar maken en resultaten controleren. De voorbeelden zijn
een beginpunt om mijn niveau te beoordelen; ze bewijzen geen zelfstandig
expertniveau.

## Gebruikt of onderzocht in grotere projecten

| Technologie of werkwijze | Beschikbaar bewijs | Nog te laten zien |
| --- | --- | --- |
| TypeScript, React, Next.js, tRPC, Zod | Broncode van de marktplaats onderzocht | Een verzoek door de applicatie volgen en een wijziging na review opleveren |
| SQL, Prisma, PostgreSQL, transacties | Schema's, migraties en transacties in de broncode | Migraties en herstel in een gedeelde omgeving uitvoeren |
| Supabase en Stripe | Integratiecode aanwezig; enkele stappen onaf | Aanmelden, betalen en annuleren volledig in een sandbox doorlopen |
| MCP en JSON-RPC | Probes, testserver en gatewaywerk | Verzoeken doorsturen en geweigerde toegang testen |
| REST-API's en eventdata | Monitoringvoorbeeld en onderzoeksbroncode | Een integratie ondersteunen met afgesproken verwachtingen |
| Lokale planning en diagnose | Oorspronkelijke monitoring- en onderzoeksscripts | Deployment, rollback en incidentafhandeling met een team |
| Git en GitHub Actions | Commits en geslaagde controles op GitHub | Pull requests met review en bijdragen in een ontwikkelteam |
| Model-API's en ontwikkelen met AI | Kleine OpenRouter-client en projectwerk | Een nuttige modelfunctie toetsen aan vooraf apart gehouden voorbeelden |

## Gebieden waarin meer ervaring nodig is

Dit portfolio toont nog geen diepgang in Docker, cloudinfrastructuur,
infrastructure as code, vectordatabases, RAG, modeltraining, fine-tuning
of grootschalige gedistribueerde systemen. Ook langdurig gebruik door
klanten en opleveren binnen een professioneel team zijn nog niet aangetoond.

## Een praktisch leerpad

| Volgende stap | Wanneer is die afgerond? |
| --- | --- |
| Een bestaand voorbeeld uitleggen en aanpassen | Gedrag doorlopen, een afgesproken wijziging maken en de test toelichten |
| Eén kleine integratie opleveren | Acceptatiecriteria afspreken, verkeerde invoer en een storing opvangen, gebruiker laten beoordelen |
| Samenwerken via Git | Een issue, branch, pull request, review en geslaagde controles met duidelijke overdracht |
| Deployment en herstel oefenen | Dezelfde toepassing deployen, configuratie documenteren en een rollback uitvoeren |
| AI toevoegen waar dat helpt | Een modelfunctie vergelijken met een eenvoudige aanpak op apart gehouden voorbeelden |

Dit zijn ontwikkelstappen. Ze zijn nog niet allemaal uitgevoerd en vormen
geen toezegging om vijf nieuwe projecten te starten.

[Werkwijze](how-i-work.nl.md) · [Profiel](application-profile.nl.md) · [Startpagina](../README.md)
