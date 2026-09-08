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
    assert "1.26.4-asian-source-ev" in recovery
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
    assert "1.26.4-asian-source-ev" in recovery


def test_match_view_honors_dark_theme_and_compacts_section_titles():
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(
        encoding="utf-8"
    )
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")

    assert "OH_MATCH_THEME_AND_TITLES_V22" in styles
    assert ':root[data-theme="dark"].match-reference-light' in styles
    assert '.summary-card-head h3,' in styles
    assert '.expected-values-panel>h3,' in styles
    assert '.one-x-title{' in styles
    assert 'font-size:13px;' in styles
    assert 'getPropertyValue("--text")' in script
    assert 'getPropertyValue("--muted")' in script
    assert 'MATCH_THEME_MARKER = "OH_MATCH_THEME_AND_TITLES_V22"' in recovery
    assert "1.26.4-asian-source-ev" in recovery


def test_picks_read_persisted_current_odds_and_all_picks_schema():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(encoding="utf-8")
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")

    assert "price?.current_odds??price?.source_odds??price?.odds" in script
    assert "Array.isArray(value.all_picks)?value.all_picks:[]" in script
    assert "pick?.current_odds??pick?.odds" in script
    assert "app.js?v=1.26.4-asian-source-ev" in recovery
    assert "app.css?v=1.26.4-asian-source-ev" in recovery
    assert "oh-mobile-v1-26-3-all-probability-picks" in recovery
    assert 'sw.js?v=1.26.4-asian-source-ev' in recovery
    assert 'name="oddshunter-build" content="1.26.4-asian-source-ev"' in recovery
    assert 'dataset.oddshunterBuild="1.26.4-asian-source-ev"' in script
    assert 'ohPickGroup("Ambos marcan"' in script
    assert 'ohPickGroup("Gol en primera mitad"' in script
    assert 'return Number.isFinite(n)&&n>1?n.toFixed(2):"—"' in script
    assert 'mapped=price?.price_origin==="ASIAN_MAPPED"' in script
    assert "Number.isFinite(sourceEv)?sourceEv*100:mapped?null" in script
    assert "OH_ASIAN_SOURCE_EV_V24" in script
    assert 'const halfLineKeys=prefix=>Object.keys(probabilities)' in script
    assert 'goalsKeys=halfLineKeys("goals"),cardsKeys=halfLineKeys("cards"),cornerKeys=halfLineKeys("corners")' in script
    assert '.filter(p=>p.odds)' not in script
    assert '.filter(p=>p.ev!==null)' not in script


def test_picks_tab_is_inserted_and_verified_in_deployment():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(encoding="utf-8")
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(encoding="utf-8")
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "oddshunter-vercel-frontend-v1.yml").read_text(encoding="utf-8")

    assert "OH_VALUE_PICKS_V23" in script
    assert "OH_VALUE_PICKS_V23" in styles
    assert 'data-tab="picks"' in recovery
    assert workflow.count("OH_VALUE_PICKS_V23") >= 4
