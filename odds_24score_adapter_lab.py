"""24score public HTML adapter for research only, never a commercial release.

Quotes aren't attributed to a named bookmaker or their original update time.
Market pairs are still useful to test parsing and coverage, but must NOT reach
OddsHunter's priced EV/publication pipeline without contractual permission.
"""
from datetime import datetime
from odds_cascade_lab import Fixture, Quote, Provider, collect_chain
from audit_24score_coverage_lab import extract_pairs


PROVIDER_NAME="24score-lab"
BOOKMAKER_NOT_IDENTIFIED="UNATTRIBUTED"


def parse_24score_fixture(html: str, fixture: Fixture, *, retrieved_at: datetime,
                          url: str) -> list[Quote]:
    if not url.startswith("https://m.24score.com/football/match/"):
        raise ValueError("unexpected URL")
    quotes=[]
    by_market=extract_pairs(html)
    for market in ("goals","corners","cards"):
        for row in by_market[market]:
            line=float(row["line"])
            for side in ("over","under"):
                quotes.append(Quote(
                    fixture_id=fixture.id,home=fixture.home,away=fixture.away,
                    kickoff=fixture.kickoff,market=market,selection=side,
                    line=line,odds=row[side],bookmaker=BOOKMAKER_NOT_IDENTIFIED,
                    source=PROVIDER_NAME,captured_at=retrieved_at,source_url=url,
                ))
    return quotes


def research_chain(fixture: Fixture, html: str, *, retrieved_at: datetime,
                   url: str):
    provider=Provider(PROVIDER_NAME,
        lambda f: parse_24score_fixture(html,f,retrieved_at=retrieved_at,url=url),
        commercial_rights_verified=False)
    return collect_chain(fixture,[provider],now=retrieved_at,commercial=True)


def coverage_preview(fixture: Fixture, html: str, *, retrieved_at: datetime,
                     url: str):
    """Report the research sample; NEVER claim this authorizes publishing."""
    provider=Provider(PROVIDER_NAME,
        lambda f: parse_24score_fixture(html,f,retrieved_at=retrieved_at,url=url),
        commercial_rights_verified=False)
    return collect_chain(fixture,[provider],now=retrieved_at,commercial=False)
