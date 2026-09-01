from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_normal_views_keep_the_compact_home_shell():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(
        encoding="utf-8"
    )

    assert "OH_COMPACT_SECONDARY_VIEWS_V20" in script
    assert 'new Set(["match","lineups"])' in script
    assert 'classList.toggle("oh-home-mode",compactShell)' in script


def test_live_upcoming_and_profile_have_compact_mobile_rules():
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(
        encoding="utf-8"
    )

    assert "OH_COMPACT_SECONDARY_VIEWS_V20" in styles
    assert ':is([data-view="live"],[data-view="upcoming"]) .match-card' in styles
    assert ':is([data-view="live"],[data-view="upcoming"]) .probability-bar' in styles
    assert '[data-view="profile"] .profile-card' in styles
    assert '[data-view="profile"] .primary-button' in styles


def test_deployment_requires_the_compact_secondary_marker():
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "oddshunter-vercel-frontend-v1.yml"
    ).read_text(encoding="utf-8")

    assert 'COMPACT_SECONDARY_MARKER = "OH_COMPACT_SECONDARY_VIEWS_V20"' in recovery
    assert "1.17.0-match-summary-compact" in recovery
    assert workflow.count("OH_COMPACT_SECONDARY_VIEWS_V20") >= 3


def test_match_summary_uses_the_compact_centered_reference():
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(
        encoding="utf-8"
    )
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")

    assert "OH_MATCH_SUMMARY_COMPACT_REFERENCE_V21" in styles
    assert '.summary-metric-title{width:100%;justify-content:center' in styles
    assert '.summary-lead{width:100%;margin:6px 0 2px;color:var(--muted)' in styles
    assert '.summary-primary-value{width:100%;margin:0' in styles
    assert 'MATCH_SUMMARY_COMPACT_MARKER = "OH_MATCH_SUMMARY_COMPACT_REFERENCE_V21"' in recovery
    assert "1.17.0-match-summary-compact" in recovery
