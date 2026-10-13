"""
rekenkern.py — Maximale-hypotheekberekening volgens de Tijdelijke regeling
hypothecair krediet (Trhk), nabouw van 'Maximale_hypotheek_2026_FinanZen.numbers'.

Ontwerp:
  * Geen afhankelijkheden van Flask of de database — pure rekenlogica.
    Daardoor herbruikbaar in de lokale CRM (Scherm 3) én later in een
    publiek webportaal.
  * Normtabellen (financieringslastpercentages, rentebanden, energielabel-
    bedragen) staan per normjaar in een JSON-bestand naast deze module
    (normtabellen_<jaar>.json), zodat jaarlijkse actualisatie geen
    codewijziging vraagt.
  * Python 3.9-compatibel (zie README: from __future__ import annotations).

Rekenstappen (identiek aan het rekenblad):
  1.  Toetsinkomen        = inkomen 1 + inkomen 2
  2.  Toetsrente          = rente, of max(rente, 5%) bij rentevast < 10 jaar
  3.  Rentebandindex      = band waarin de toetsrente valt (bovengrenzen-tabel)
  4.  Energielabelbedrag  = opslag op basis van het energielabel
  5.  Studieschuldlast    = wegingsfactor (0,65% oud / 0,35% nieuw) x
                            oorspronkelijke schuld, per maand
  6.  Jaarverplichtingen  = (BKR-lasten + alimentatie + studieschuldlast) x 12
  7.  Annuiteitenfactor   = PMT(toetsrente/12, 360, -1) x 12
  8.  FL%                 = tabel-lookup op (afgekapt toetsinkomen, renteband),
                            gewogen over aftrekbaar / niet-aftrekbaar deel
  9.  Budget              = max(toetsinkomen x FL% - jaarverplichtingen, 0)
  10. Max o.b.v. inkomen  = budget / annuiteitenfactor + energielabelbedrag
  11. Pensioentoets       = zelfde berekening met pensioeninkomen en
                            tabellen 2/4, alleen bij AOW binnen 10 jaar;
                            bindend is dan het minimum van beide.
  12. Maximale hypotheek  = min(max o.b.v. inkomen, woningwaarde x 100%)

NB: bekende bevinding — het aangeleverde rekenblad lijkt op de doelmachine
de renteband niet goed te bepalen (COUNTIF-uitkomst 0), waardoor de cache-
waarden band 1 gebruiken. Deze module implementeert de bedoelde logica;
zie tests/test_rekenkern.py voor de vergelijkingstabel.
"""
from __future__ import annotations

import json
import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Sleutels zoals in de invoer/JSON
LEENSTELSEL_OUD = 'oud'      # studieschuld vóór 1-9-2015 (0,65%)
LEENSTELSEL_NIEUW = 'nieuw'  # studieschuld na 1-9-2015 (0,35%)

ENERGIELABELS = ['E,F,G', 'C,D', 'A,B', 'A+,A++', 'A+++', 'A++++']


class RekenkernFout(ValueError):
    """Ongeldige invoer of ontbrekende normtabel."""


def laad_normtabellen(normjaar: int = 2026) -> dict:
    pad = os.path.join(BASE_DIR, f'normtabellen_{normjaar}.json')
    if not os.path.exists(pad):
        raise RekenkernFout(f'Geen normtabellen voor {normjaar} ({pad} ontbreekt).')
    with open(pad, encoding='utf-8') as f:
        return json.load(f)


# ── Bouwstenen ───────────────────────────────────────────────────────────────

def bepaal_toetsrente(rente_pct: float, rentevast_10jr: bool, minimum_kort: float) -> float:
    """5%-regel: bij rentevast < 10 jaar geldt minimaal de wettelijke toetsrente."""
    if rente_pct <= 0:
        raise RekenkernFout('Hypotheekrente moet groter dan 0 zijn.')
    return rente_pct if rentevast_10jr else max(rente_pct, minimum_kort)


def bepaal_rentebandindex(toetsrente_pct: float, bovengrenzen: list) -> int:
    """Geeft 0-gebaseerde kolomindex in de FL-tabellen.

    Bovengrenzen [1.5, 2.0, ... 6.5]: rente <= 1,5 -> band 0;
    1,501-2,0 -> band 1; ... ; > 6,5 -> band 11 (laatste kolom).
    (Rekenblad: COUNTIF(banden; "<" & toetsrente), waarbij een rente die
    precies op een grens valt in de band ónder die grens hoort.)
    """
    idx = sum(1 for grens in bovengrenzen if grens < toetsrente_pct)
    return min(idx, len(bovengrenzen))  # boven 6,5% -> hoogste band


def bepaal_energielabelbedrag(label: str, bedragen: dict) -> float:
    if label not in bedragen:
        raise RekenkernFout(
            f"Onbekend energielabel '{label}'. Kies uit: {', '.join(bedragen)}.")
    return float(bedragen[label])


def fictieve_maandlast_studieschuld(oorspronkelijke_schuld: float,
                                    leenstelsel: str, wegingen: dict) -> float:
    if oorspronkelijke_schuld <= 0:
        return 0.0
    if leenstelsel not in wegingen:
        raise RekenkernFout("Leenstelsel moet 'oud' of 'nieuw' zijn.")
    return oorspronkelijke_schuld * wegingen[leenstelsel]


def annuiteitenfactor(toetsrente_pct: float, looptijd_maanden: int = 360) -> float:
    """PMT(rente/12, n, -1) x 12: jaarlast per euro hypotheek."""
    r = toetsrente_pct / 100.0 / 12.0
    if r == 0:
        return 12.0 / looptijd_maanden
    pmt = r / (1.0 - (1.0 + r) ** -looptijd_maanden)
    return pmt * 12.0


def _fl_lookup(tabel: dict, toetsinkomen: float, bandindex: int) -> float:
    """Zoekt het financieringslastpercentage.

    Rijen zijn inkomens in stappen; het inkomen wordt afgekapt op de
    tabelgrenzen en daarna naar beneden afgerond op de dichtstbijzijnde
    tabelrij (MATCH-type 1 in het rekenblad).
    """
    inkomens = sorted(int(k) for k in tabel.keys())
    laag, hoog = inkomens[0], inkomens[-1]
    ink = min(max(toetsinkomen, laag), hoog)
    rij = max(i for i in inkomens if i <= ink)
    return float(tabel[str(rij)][bandindex])


def gewogen_fl_pct(fl_aftrekbaar: float, fl_niet_aftrekbaar: float,
                   niet_aftrekbaar_deel_pct: float) -> float:
    w = niet_aftrekbaar_deel_pct / 100.0
    if not 0.0 <= w <= 1.0:
        raise RekenkernFout('Niet-aftrekbaar deel moet tussen 0 en 100% liggen.')
    return (1.0 - w) * fl_aftrekbaar + w * fl_niet_aftrekbaar


# ── Hoofdberekening ──────────────────────────────────────────────────────────

def bereken_maximale_hypotheek(
    bruto_jaarinkomen_1: float,
    bruto_jaarinkomen_2: float = 0.0,
    rente_pct: float = 0.0,
    rentevast_10jr: bool = True,
    woningwaarde: float = 0.0,
    energielabel: str = 'C,D',
    niet_aftrekbaar_deel_pct: float = 0.0,
    maandlasten_bkr: float = 0.0,
    alimentatie_pm: float = 0.0,
    studieschuld_oorspronkelijk: float = 0.0,
    leenstelsel: str = LEENSTELSEL_NIEUW,
    aow_binnen_10jr: bool = False,
    pensioeninkomen_jaar: float = 0.0,
    normjaar: int = 2026,
    normtabellen: Optional[dict] = None,
) -> dict:
    """Berekent de maximale hypotheek. Geeft een dict met de uitkomst én alle
    tussenstappen (voor het controlescherm en de validatie tegen het rekenblad).
    """
    nt = normtabellen or laad_normtabellen(normjaar)
    banden = nt['renteband_bovengrenzen']
    fl = nt['fl_tabellen']

    if bruto_jaarinkomen_1 < 0 or bruto_jaarinkomen_2 < 0:
        raise RekenkernFout('Inkomen kan niet negatief zijn.')
    if woningwaarde <= 0:
        raise RekenkernFout('Woningwaarde/koopsom moet groter dan 0 zijn.')

    # 1-7: bouwstenen
    toetsinkomen = bruto_jaarinkomen_1 + bruto_jaarinkomen_2
    toetsrente = bepaal_toetsrente(rente_pct, rentevast_10jr,
                                   nt['toetsrente_minimum_kort'])
    band = bepaal_rentebandindex(toetsrente, banden)
    label_bedrag = bepaal_energielabelbedrag(energielabel,
                                             nt['energielabel_bedragen'])
    studielast_pm = fictieve_maandlast_studieschuld(
        studieschuld_oorspronkelijk, leenstelsel, nt['studieschuld_weging'])
    verplichtingen_pj = (maandlasten_bkr + alimentatie_pm + studielast_pm) * 12.0
    ann_factor = annuiteitenfactor(toetsrente, nt['looptijd_maanden'])

    # 8-10: huidig inkomen
    fl_a = _fl_lookup(fl['huidig_aftrekbaar'], toetsinkomen, band)
    fl_na = _fl_lookup(fl['huidig_niet_aftrekbaar'], toetsinkomen, band)
    fl_pct = gewogen_fl_pct(fl_a, fl_na, niet_aftrekbaar_deel_pct)
    budget_nu = max(toetsinkomen * fl_pct / 100.0 - verplichtingen_pj, 0.0)
    max_nu = budget_nu / ann_factor + label_bedrag

    # 11: pensioentoets
    pensioen = None
    max_inkomen = max_nu
    if aow_binnen_10jr:
        fl_pa = _fl_lookup(fl['pensioen_aftrekbaar'], pensioeninkomen_jaar, band)
        fl_pna = _fl_lookup(fl['pensioen_niet_aftrekbaar'], pensioeninkomen_jaar, band)
        fl_p = gewogen_fl_pct(fl_pa, fl_pna, niet_aftrekbaar_deel_pct)
        budget_p = max(pensioeninkomen_jaar * fl_p / 100.0 - verplichtingen_pj, 0.0)
        max_p = budget_p / ann_factor + label_bedrag
        pensioen = {
            'fl_pct_aftrekbaar': fl_pa, 'fl_pct_niet_aftrekbaar': fl_pna,
            'fl_pct_gewogen': round(fl_p, 4),
            'budget_financieringslast': round(budget_p, 2),
            'max_obv_pensioeninkomen': round(max_p, 2),
        }
        max_inkomen = min(max_nu, max_p)

    # 12: woningwaardegrens (LTV 100%)
    max_woningwaarde = woningwaarde * 1.0
    maximale_hypotheek = min(max_inkomen, max_woningwaarde)

    return {
        'normjaar': nt['normjaar'],
        'invoer': {
            'bruto_jaarinkomen_1': bruto_jaarinkomen_1,
            'bruto_jaarinkomen_2': bruto_jaarinkomen_2,
            'rente_pct': rente_pct, 'rentevast_10jr': rentevast_10jr,
            'woningwaarde': woningwaarde, 'energielabel': energielabel,
            'niet_aftrekbaar_deel_pct': niet_aftrekbaar_deel_pct,
            'maandlasten_bkr': maandlasten_bkr, 'alimentatie_pm': alimentatie_pm,
            'studieschuld_oorspronkelijk': studieschuld_oorspronkelijk,
            'leenstelsel': leenstelsel, 'aow_binnen_10jr': aow_binnen_10jr,
            'pensioeninkomen_jaar': pensioeninkomen_jaar,
        },
        'tussenstappen': {
            'toetsinkomen': round(toetsinkomen, 2),
            'toetsrente_pct': toetsrente,
            'rentebandindex': band + 1,          # 1-gebaseerd, zoals het rekenblad
            'energielabel_bedrag': label_bedrag,
            'studieschuld_maandlast': round(studielast_pm, 2),
            'verplichtingen_per_jaar': round(verplichtingen_pj, 2),
            'annuiteitenfactor': ann_factor,
            'fl_pct_aftrekbaar': fl_a,
            'fl_pct_niet_aftrekbaar': fl_na,
            'fl_pct_gewogen': round(fl_pct, 4),
            'budget_financieringslast': round(budget_nu, 2),
            'max_obv_inkomen_nu': round(max_nu, 2),
            'pensioentoets': pensioen,
        },
        'uitkomst': {
            'max_obv_inkomen': round(max_inkomen, 2),
            'max_obv_woningwaarde': round(max_woningwaarde, 2),
            'maximale_hypotheek': round(maximale_hypotheek, 2),
            'begrenzing': 'inkomen' if max_inkomen <= max_woningwaarde else 'woningwaarde',
        },
    }


# ── Opties náást de Excel-uitkomst (nooit in plaats van) ─────────────────────

def nhg_toets(koopsom: float, energiebesparende_voorzieningen: bool,
              normtabellen: Optional[dict] = None, normjaar: int = 2026) -> dict:
    """NHG-grenstoets: valt de koopsom binnen de NHG-kostengrens, en wat is
    de premie (borgtochtprovisie)? Aparte toets naast de Excel-uitkomst."""
    nt = normtabellen or laad_normtabellen(normjaar)
    nhg = nt.get('nhg')
    if not nhg:
        raise RekenkernFout(f'Geen NHG-waarden in normtabellen {normjaar}.')
    grens = nhg['kostengrens_ebv'] if energiebesparende_voorzieningen \
        else nhg['kostengrens']
    mogelijk = koopsom <= grens
    return {
        'normjaar': nt['normjaar'],
        'kostengrens_toegepast': grens,
        'nhg_mogelijk': mogelijk,
        'premie_pct': nhg['premie_pct'],
        'premie_bedrag': round(koopsom * nhg['premie_pct'] / 100.0, 2) if mogelijk else None,
    }


def studieschuld_wettelijk(werkelijke_maandlast: float, toetsrente_pct: float,
                           normtabellen: Optional[dict] = None,
                           normjaar: int = 2026) -> float:
    """Wettelijke studieschuldmethode (sinds 2024): werkelijke maandlast x
    bruteringsfactor afhankelijk van de toetsrente. Vereist dat de
    bruteringsfactoren in de normtabellen zijn ingevuld (Trhk-bijlage)."""
    nt = normtabellen or laad_normtabellen(normjaar)
    factoren = nt.get('studieschuld_bruteringsfactoren')
    if not factoren:
        raise RekenkernFout(
            'Bruteringsfactoren voor de wettelijke studieschuldmethode zijn nog '
            'niet ingevuld in de normtabellen. Vul ze in vanuit de Trhk-bijlage '
            '(Staatscourant) via Instellingen; tot die tijd is alleen de '
            'Excel-methode (wegingsfactor) beschikbaar.')
    # factoren: lijst van [bovengrens_toetsrente_pct, factor], oplopend
    for bovengrens, factor in factoren:
        if toetsrente_pct <= bovengrens:
            return werkelijke_maandlast * factor
    return werkelijke_maandlast * factoren[-1][1]
