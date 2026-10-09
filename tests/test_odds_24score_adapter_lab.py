import unittest
from datetime import datetime, timedelta, timezone
from odds_cascade_lab import Fixture
from odds_24score_adapter_lab import (parse_24score_fixture, research_chain, coverage_preview)

NOW=datetime(2026,10,9,8,0,tzinfo=timezone.utc)
FIXTURE=Fixture("854861","Arsenal","Leeds",NOW+timedelta(days=1))
URL="https://m.24score.com/football/match/854861-arsenal-leeds"
HTML="""
<h3>Total Goals 2.5</h3><table><tr><td>Over</td><td>Under</td></tr>
<tr><td>1.833</td><td>1.99</td></tr></table>
<h3>Total Corners 9.5</h3><table><tr><td>Over</td><td>Under</td></tr>
<tr><td>1.81</td><td>1.89</td></tr></table>
<h3>Total YC 4.5</h3><table><tr><td>Over</td><td>Under</td></tr>
<tr><td></td><td></td></tr></table>
"""

class SourceLabTests(unittest.TestCase):
    def test_parses_only_explicit_pairs(self):
        rows=parse_24score_fixture(HTML,FIXTURE,retrieved_at=NOW,url=URL)
        self.assertEqual(len(rows),4)
        self.assertEqual({q.market for q in rows},{"goals","corners"})
        self.assertEqual({q.bookmaker for q in rows},{"UNATTRIBUTED"})
        self.assertNotIn("btts",{q.market for q in rows})

    def test_no_commercial_publish_even_when_raw_pairs_exist(self):
        report=research_chain(FIXTURE,HTML,retrieved_at=NOW,url=URL)
        self.assertFalse(report["can_publish"])
        self.assertEqual(report["status"],"FAIL_PARTIAL")
        self.assertEqual(report["providers_checked"]["24score-lab"],"LICENSE_NOT_VERIFIED")

    def test_research_preview_shows_gaps_without_inventing(self):
        report=coverage_preview(FIXTURE,HTML,retrieved_at=NOW,url=URL)
        self.assertEqual(set(report["markets"]),{"goals","corners"})
        self.assertEqual(set(report["missing"]),{"cards","btts"})
        self.assertFalse(report["can_publish"])

    def test_wrong_domain_refused(self):
        with self.assertRaises(ValueError):
            parse_24score_fixture(HTML,FIXTURE,retrieved_at=NOW,url="https://example.com/")

if __name__=="__main__":unittest.main()
