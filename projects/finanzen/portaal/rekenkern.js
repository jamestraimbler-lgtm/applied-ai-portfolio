/* rekenkern.js — 1-op-1 port van finanzen_app/rekenkern.py (Trhk 2026).
   Draait volledig in de browser; er wordt niets verstuurd. */

function bepaalToetsrente(rentePct, rentevast10jr, minimumKort) {
  if (rentePct <= 0) throw new Error('Hypotheekrente moet groter dan 0 zijn.');
  return rentevast10jr ? rentePct : Math.max(rentePct, minimumKort);
}

function bepaalRentebandindex(toetsrentePct, bovengrenzen) {
  let idx = 0;
  for (const grens of bovengrenzen) if (grens < toetsrentePct) idx++;
  return Math.min(idx, bovengrenzen.length); // boven 6,5% -> hoogste band
}

function bepaalEnergielabelbedrag(label, bedragen) {
  if (!(label in bedragen)) throw new Error(`Onbekend energielabel '${label}'.`);
  return Number(bedragen[label]);
}

function fictieveMaandlastStudieschuld(oorspronkelijkeSchuld, leenstelsel, wegingen) {
  if (oorspronkelijkeSchuld <= 0) return 0;
  if (!(leenstelsel in wegingen)) throw new Error("Leenstelsel moet 'oud' of 'nieuw' zijn.");
  return oorspronkelijkeSchuld * wegingen[leenstelsel];
}

function annuiteitenfactor(toetsrentePct, looptijdMaanden = 360) {
  const r = toetsrentePct / 100 / 12;
  if (r === 0) return 12 / looptijdMaanden;
  const pmt = r / (1 - Math.pow(1 + r, -looptijdMaanden));
  return pmt * 12;
}

function flLookup(tabel, toetsinkomen, bandindex) {
  const inkomens = Object.keys(tabel).map(Number).sort((a, b) => a - b);
  const laag = inkomens[0], hoog = inkomens[inkomens.length - 1];
  const ink = Math.min(Math.max(toetsinkomen, laag), hoog);
  let rij = laag;
  for (const i of inkomens) if (i <= ink) rij = i;
  return Number(tabel[String(rij)][bandindex]);
}

function gewogenFlPct(flAftrekbaar, flNietAftrekbaar, nietAftrekbaarDeelPct) {
  const w = nietAftrekbaarDeelPct / 100;
  if (w < 0 || w > 1) throw new Error('Niet-aftrekbaar deel moet tussen 0 en 100% liggen.');
  return (1 - w) * flAftrekbaar + w * flNietAftrekbaar;
}

const rond2 = (x) => Math.round(x * 100) / 100;
const rond4 = (x) => Math.round(x * 10000) / 10000;

function berekenMaximaleHypotheek(inv, nt) {
  const banden = nt.renteband_bovengrenzen;
  const fl = nt.fl_tabellen;
  const i1 = inv.brutoJaarinkomen1 || 0, i2 = inv.brutoJaarinkomen2 || 0;
  if (i1 < 0 || i2 < 0) throw new Error('Inkomen kan niet negatief zijn.');
  if (!(inv.woningwaarde > 0)) throw new Error('Woningwaarde/koopsom moet groter dan 0 zijn.');

  const toetsinkomen = i1 + i2;
  const toetsrente = bepaalToetsrente(inv.rentePct, inv.rentevast10jr,
                                      nt.toetsrente_minimum_kort);
  const band = bepaalRentebandindex(toetsrente, banden);
  const labelBedrag = bepaalEnergielabelbedrag(inv.energielabel, nt.energielabel_bedragen);
  const studielastPm = fictieveMaandlastStudieschuld(
    inv.studieschuldOorspronkelijk || 0, inv.leenstelsel || 'nieuw',
    nt.studieschuld_weging);
  const verplichtingenPj = ((inv.maandlastenBkr || 0) + (inv.alimentatiePm || 0)
                            + studielastPm) * 12;
  const annFactor = annuiteitenfactor(toetsrente, nt.looptijd_maanden);

  const flA = flLookup(fl.huidig_aftrekbaar, toetsinkomen, band);
  const flNa = flLookup(fl.huidig_niet_aftrekbaar, toetsinkomen, band);
  const flPct = gewogenFlPct(flA, flNa, inv.nietAftrekbaarDeelPct || 0);
  const budgetNu = Math.max(toetsinkomen * flPct / 100 - verplichtingenPj, 0);
  const maxNu = budgetNu / annFactor + labelBedrag;

  let pensioen = null;
  let maxInkomen = maxNu;
  if (inv.aowBinnen10jr) {
    const p = inv.pensioeninkomenJaar || 0;
    const flPa = flLookup(fl.pensioen_aftrekbaar, p, band);
    const flPna = flLookup(fl.pensioen_niet_aftrekbaar, p, band);
    const flP = gewogenFlPct(flPa, flPna, inv.nietAftrekbaarDeelPct || 0);
    const budgetP = Math.max(p * flP / 100 - verplichtingenPj, 0);
    const maxP = budgetP / annFactor + labelBedrag;
    pensioen = {
      fl_pct_aftrekbaar: flPa, fl_pct_niet_aftrekbaar: flPna,
      fl_pct_gewogen: rond4(flP),
      budget_financieringslast: rond2(budgetP),
      max_obv_pensioeninkomen: rond2(maxP),
    };
    maxInkomen = Math.min(maxNu, maxP);
  }

  const maxWoningwaarde = inv.woningwaarde * 1.0;
  const maximaleHypotheek = Math.min(maxInkomen, maxWoningwaarde);

  return {
    tussenstappen: {
      toetsinkomen: rond2(toetsinkomen),
      toetsrente_pct: toetsrente,
      rentebandindex: band + 1,
      energielabel_bedrag: labelBedrag,
      studieschuld_maandlast: rond2(studielastPm),
      verplichtingen_per_jaar: rond2(verplichtingenPj),
      annuiteitenfactor: annFactor,
      fl_pct_aftrekbaar: flA,
      fl_pct_niet_aftrekbaar: flNa,
      fl_pct_gewogen: rond4(flPct),
      budget_financieringslast: rond2(budgetNu),
      max_obv_inkomen_nu: rond2(maxNu),
      pensioentoets: pensioen,
    },
    uitkomst: {
      max_obv_inkomen: rond2(maxInkomen),
      max_obv_woningwaarde: rond2(maxWoningwaarde),
      maximale_hypotheek: rond2(maximaleHypotheek),
      begrenzing: maxInkomen <= maxWoningwaarde ? 'inkomen' : 'woningwaarde',
    },
  };
}

function nhgToets(koopsom, ebv, nt) {
  const nhg = nt.nhg;
  const grens = ebv ? nhg.kostengrens_ebv : nhg.kostengrens;
  const mogelijk = koopsom <= grens;
  return {
    kostengrens_toegepast: grens,
    nhg_mogelijk: mogelijk,
    premie_pct: nhg.premie_pct,
    premie_bedrag: mogelijk ? rond2(koopsom * nhg.premie_pct / 100) : null,
  };
}

if (typeof module !== 'undefined') {
  module.exports = { berekenMaximaleHypotheek, nhgToets };
}
