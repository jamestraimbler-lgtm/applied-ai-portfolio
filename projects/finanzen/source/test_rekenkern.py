"""
test_rekenkern.py — tests voor de maximale-hypotheekberekening.

Draaien:  venv/bin/python -m unittest test_rekenkern -v   (vanuit finanzen_app/)
Geen extra pakketten nodig (alleen de standaardbibliotheek).

De verwachte waarden zijn met de hand nagerekend volgens de formuleketen
uit het rekenblad 'Maximale_hypotheek_2026_FinanZen.numbers'. De definitieve
euro-exacte validatie tegen het rekenblad zelf gebeurt met
valideer_rekenblad.py (zie de vergelijkingstabel die dat script maakt).
"""
from __future__ import annotations

import unittest

import rekenkern as rk

NT = rk.laad_normtabellen(2026)


class TestBouwstenen(unittest.TestCase):

    def test_toetsrente_5_procent_regel(self):
        self.assertEqual(rk.bepaal_toetsrente(4.01, True, 5.0), 4.01)
        self.assertEqual(rk.bepaal_toetsrente(4.01, False, 5.0), 5.0)
        self.assertEqual(rk.bepaal_toetsrente(6.2, False, 5.0), 6.2)

    def test_rentebandindex_grenzen(self):
        banden = NT['renteband_bovengrenzen']
        # Precies op een grens hoort bij de band ónder die grens
        self.assertEqual(rk.bepaal_rentebandindex(1.5, banden), 0)
        self.assertEqual(rk.bepaal_rentebandindex(1.501, banden), 1)
        self.assertEqual(rk.bepaal_rentebandindex(4.0, banden), 5)
        self.assertEqual(rk.bepaal_rentebandindex(4.01, banden), 6)
        # Boven de hoogste grens: laatste kolom
        self.assertEqual(rk.bepaal_rentebandindex(9.9, banden), 11)

    def test_energielabelbedrag(self):
        b = NT['energielabel_bedragen']
        self.assertEqual(rk.bepaal_energielabelbedrag('E,F,G', b), 0)
        self.assertEqual(rk.bepaal_energielabelbedrag('C,D', b), 5000)
        self.assertEqual(rk.bepaal_energielabelbedrag('A++++', b), 30000)
        with self.assertRaises(rk.RekenkernFout):
            rk.bepaal_energielabelbedrag('B+', b)

    def test_studieschuld_weging(self):
        w = NT['studieschuld_weging']
        self.assertAlmostEqual(
            rk.fictieve_maandlast_studieschuld(30000, 'oud', w), 195.0)
        self.assertAlmostEqual(
            rk.fictieve_maandlast_studieschuld(30000, 'nieuw', w), 105.0)
        self.assertEqual(rk.fictieve_maandlast_studieschuld(0, 'nieuw', w), 0.0)

    def test_annuiteitenfactor(self):
        # Waarde uit het rekenblad bij 4,01%: 0.0573590385534027
        self.assertAlmostEqual(rk.annuiteitenfactor(4.01), 0.0573590385534027,
                               places=12)
        # Renteloos: lineair 1/30 per jaar
        self.assertAlmostEqual(rk.annuiteitenfactor(0.0), 12.0 / 360.0)

    def test_fl_lookup_afkap_en_afronding(self):
        t1 = NT['fl_tabellen']['huidig_aftrekbaar']
        # Boven tabelmax (125k) afkappen
        self.assertEqual(rk._fl_lookup(t1, 133000, 6), t1['125000'][6])
        # Onder tabelmin (30k) afkappen
        self.assertEqual(rk._fl_lookup(t1, 12000, 0), t1['30000'][0])
        # Tussenwaarde naar beneden op tabelrij (MATCH type 1)
        self.assertEqual(rk._fl_lookup(t1, 34999, 3), t1['34000'][3])

    def test_gewogen_fl(self):
        self.assertAlmostEqual(rk.gewogen_fl_pct(29.2, 21.0, 0), 29.2)
        self.assertAlmostEqual(rk.gewogen_fl_pct(29.2, 21.0, 100), 21.0)
        self.assertAlmostEqual(rk.gewogen_fl_pct(30.0, 20.0, 25), 27.5)


class TestHoofdberekening(unittest.TestCase):

    def _basis(self, **kw):
        p = dict(bruto_jaarinkomen_1=61000, bruto_jaarinkomen_2=72000,
                 rente_pct=4.01, rentevast_10jr=True, woningwaarde=1_900_000,
                 energielabel='C,D')
        p.update(kw)
        return rk.bereken_maximale_hypotheek(**p)

    def test_rekenblad_invoer(self):
        """De invoer zoals in het aangeleverde rekenblad (4,01%, 61k+72k, C/D).
        Verwacht volgens de bedoelde formuleketen: band 4,001-4,5 -> FL 28,3%
        (Tabel 1, rij 125.000), budget 133.000 x 28,3% = 37.639 ->
        37.639 / 0,0573590... + 5.000 = 661.199,98."""
        r = self._basis()
        t, u = r['tussenstappen'], r['uitkomst']
        self.assertEqual(t['toetsinkomen'], 133000)
        self.assertEqual(t['rentebandindex'], 7)          # 1-gebaseerd
        self.assertEqual(t['fl_pct_aftrekbaar'], 28.3)
        self.assertEqual(t['budget_financieringslast'], 37639.0)
        self.assertAlmostEqual(u['maximale_hypotheek'], 661199.98, places=2)
        self.assertEqual(u['begrenzing'], 'inkomen')

    def test_woningwaarde_begrenst(self):
        r = self._basis(woningwaarde=250000)
        self.assertEqual(r['uitkomst']['maximale_hypotheek'], 250000.0)
        self.assertEqual(r['uitkomst']['begrenzing'], 'woningwaarde')

    def test_pensioentoets_bindend(self):
        r = self._basis(aow_binnen_10jr=True, pensioeninkomen_jaar=32000)
        p = r['tussenstappen']['pensioentoets']
        self.assertIsNotNone(p)
        # Pensioen 32k, band 7 -> Tabel 2 rij 32000 kolom 7 (index 6) = 23.8
        self.assertEqual(p['fl_pct_aftrekbaar'], 23.8)
        self.assertEqual(r['uitkomst']['max_obv_inkomen'],
                         p['max_obv_pensioeninkomen'])

    def test_zonder_aow_geen_pensioentoets(self):
        r = self._basis(aow_binnen_10jr=False, pensioeninkomen_jaar=32000)
        self.assertIsNone(r['tussenstappen']['pensioentoets'])

    def test_verplichtingen_drukken_budget(self):
        kaal = self._basis()
        met = self._basis(maandlasten_bkr=250, alimentatie_pm=300,
                          studieschuld_oorspronkelijk=30000, leenstelsel='oud')
        # (250+300+195)*12 = 8.940 minder budget per jaar
        self.assertEqual(met['tussenstappen']['verplichtingen_per_jaar'], 8940.0)
        self.assertLess(met['uitkomst']['maximale_hypotheek'],
                        kaal['uitkomst']['maximale_hypotheek'])

    def test_budget_niet_negatief(self):
        r = self._basis(bruto_jaarinkomen_1=30000, bruto_jaarinkomen_2=0,
                        maandlasten_bkr=2000)
        self.assertEqual(r['tussenstappen']['budget_financieringslast'], 0.0)
        # Alleen het energielabelbedrag blijft over
        self.assertEqual(r['tussenstappen']['max_obv_inkomen_nu'], 5000.0)

    def test_niet_aftrekbaar_deel(self):
        r = self._basis(niet_aftrekbaar_deel_pct=40)
        t = r['tussenstappen']
        verwacht = 0.6 * t['fl_pct_aftrekbaar'] + 0.4 * t['fl_pct_niet_aftrekbaar']
        self.assertAlmostEqual(t['fl_pct_gewogen'], round(verwacht, 4))

    def test_invoervalidatie(self):
        with self.assertRaises(rk.RekenkernFout):
            self._basis(woningwaarde=0)
        with self.assertRaises(rk.RekenkernFout):
            self._basis(rente_pct=0)
        with self.assertRaises(rk.RekenkernFout):
            self._basis(bruto_jaarinkomen_1=-1)
        with self.assertRaises(rk.RekenkernFout):
            self._basis(energielabel='Z')


class TestOpties(unittest.TestCase):

    def test_nhg_toets(self):
        r = rk.nhg_toets(450000, False)
        self.assertTrue(r['nhg_mogelijk'])
        self.assertEqual(r['premie_bedrag'], 1800.0)
        self.assertFalse(rk.nhg_toets(480000, False)['nhg_mogelijk'])
        self.assertTrue(rk.nhg_toets(480000, True)['nhg_mogelijk'])

    def test_wettelijke_studieschuld_nog_niet_ingevuld(self):
        with self.assertRaises(rk.RekenkernFout):
            rk.studieschuld_wettelijk(120, 4.01)


if __name__ == '__main__':
    unittest.main(verbosity=2)
