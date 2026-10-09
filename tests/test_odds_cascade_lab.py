import unittest
from datetime import datetime, timedelta, timezone
from odds_cascade_lab import Fixture, Quote, Provider, collect_chain, good_pair

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
GAME = Fixture("OH123", "Arsenal", "Leeds", NOW + timedelta(days=1))


def pair(provider, market, line, book="TestBook", captured=NOW,
         home="Arsenal", away="Leeds"):
    sides = ("yes","no") if market == "btts" else ("over","under")
    return [
        Quote(GAME.id,home,away,GAME.kickoff,market,side,line,1.80 if n==0 else 1.95,
              book,provider,captured,"https://example.org/match/123")
        for n,side in enumerate(sides)
    ]


class CascadeTests(unittest.TestCase):
    def test_first_source_only_goals_corners_second_cards_btts(self):
        calls=[]
        def a(_):
            calls.append("A")
            return pair("A","goals",2.5)+pair("A","corners",9.5)
        def b(_):
            calls.append("B")
            return pair("B","cards",4.5)+pair("B","btts",None)
        result=collect_chain(GAME,[Provider("A",a),Provider("B",b)],now=NOW)
        self.assertEqual(result["status"],"PASS_4_OF_4")
        self.assertFalse(result["can_publish"])
        self.assertEqual(calls,["A","B"])
        self.assertEqual(result["markets"]["cards"]["source"],"B")

    def test_partial_does_not_pass(self):
        result=collect_chain(GAME,[Provider("A",lambda _: pair("A","goals",2.5))],now=NOW)
        self.assertEqual(result["status"],"FAIL_PARTIAL")
        self.assertEqual(set(result["missing"]),{"corners","cards","btts"})

    def test_missing_under_rejected(self):
        self.assertIsNone(good_pair(GAME,pair("A","cards",4.5)[:1],NOW))

    def test_no_mixed_bookmakers(self):
        a=pair("A","goals",2.5)
        b=pair("A","goals",2.5,"DifferentBook")
        self.assertIsNone(good_pair(GAME,[a[0],b[1]],NOW))

    def test_no_mixed_lines(self):
        a=pair("A","corners",9.5)
        b=pair("A","corners",10.5)
        self.assertIsNone(good_pair(GAME,[a[0],b[1]],NOW))

    def test_stale_odds(self):
        self.assertIsNone(good_pair(GAME,pair("A","btts",None,captured=NOW-timedelta(hours=3)),NOW))

    def test_wrong_fixture(self):
        self.assertIsNone(good_pair(GAME,pair("A","goals",2.5,home="Arsenal",away="Spurs"),NOW))

    def test_license_gate(self):
        called=[]
        def fetch(_):
            called.append(True)
            return sum((pair("A",m, None if m=="btts" else 2.5) for m in
                        ("goals","corners","cards","btts")),[])
        blocked=collect_chain(GAME,[Provider("A",fetch)],now=NOW,commercial=True)
        self.assertFalse(blocked["can_publish"])
        self.assertEqual(blocked["providers_checked"]["A"],"LICENSE_NOT_VERIFIED")
        self.assertEqual(called,[])
        allowed=collect_chain(GAME,[Provider("A",fetch,commercial_rights_verified=True)],
                              now=NOW,commercial=True)
        self.assertTrue(allowed["can_publish"])


if __name__=="__main__":
    unittest.main()
