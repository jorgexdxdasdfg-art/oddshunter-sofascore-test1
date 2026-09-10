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
    assert "1.30.1-complete-ev-top60" in recovery
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
    assert "1.30.1-complete-ev-top60" in recovery


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
    assert "1.30.1-complete-ev-top60" in recovery


def test_picks_read_persisted_current_odds_and_all_picks_schema():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(encoding="utf-8")
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")

    assert "price?.current_odds??price?.source_odds??price?.estimated_odds??price?.odds" in script
    assert "Array.isArray(value.all_picks)?value.all_picks:[]" in script
    assert "pick?.current_odds??pick?.source_odds??pick?.estimated_odds??pick?.odds" in script
    assert "app.js?v=1.30.1-complete-ev-top60" in recovery
    assert "app.css?v=1.30.1-complete-ev-top60" in recovery
    assert "oh-mobile-v1-30-1-complete-ev-top60" in recovery
    assert 'sw.js?v=1.30.1-complete-ev-top60' in recovery
    assert 'name="oddshunter-build" content="1.30.1-complete-ev-top60"' in recovery
    assert 'dataset.oddshunterBuild="1.30.1-complete-ev-top60"' in script
    assert 'ohPickGroup("Ambos marcan"' in script
    assert 'ohPickGroup("Gol en primera mitad"' in script
    assert 'const exact=n.toFixed(3);return exact.endsWith("0")?n.toFixed(2):exact' in script
    assert "OH_BET365_ANCHORED_ESTIMATES_V27" in script
    assert 'return "Est. desde Bet365"' in script
    assert 'estimatedEv=price?.estimated_ev==null?NaN:Number(price.estimated_ev)' in script
    assert 'Number.isFinite(estimatedEv)?estimatedEv*100' in script
    assert 'cardsKeys=halfLineKeys("cards").filter(key=>!/_0_5$/.test(key))' in script
    assert 'pick?.estimated_odds??pick?.odds' in script
    assert "OH_REAL_ODDS_PRECISION_V26" in script
    assert 'mapped=price?.price_origin==="ASIAN_MAPPED"' in script
    assert "Number.isFinite(sourceEv)?sourceEv*100:Number.isFinite(estimatedEv)?estimatedEv*100:mapped?null" in script
    assert "OH_ASIAN_SOURCE_EV_V24" in script
    assert "OH_UNDER_SOURCE_LABEL_V25" in script
    assert "function ohSourceBetLabel(price)" in script
    assert 'return `Bet365 ${side==="over"?"O":"U"}${sourceLine}`' in script
    assert "${ohSourceBetTag(price)}" in script
    assert "${ohSourceBetTag(pick)}" in script
    assert 'const halfLineKeys=prefix=>Object.keys(probabilities)' in script
    assert 'goalsKeys=halfLineKeys("goals"),cardsKeys=halfLineKeys("cards").filter(key=>!/_0_5$/.test(key)),cornerKeys=halfLineKeys("corners")' in script
    assert '.filter(p=>p.odds)' not in script
    assert '.filter(p=>p.ev!==null)' not in script


def test_v28_mobile_orders_corners_and_renders_original_final_pick_values():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(encoding="utf-8")
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "oddshunter-vercel-frontend-v1.yml").read_text(encoding="utf-8")

    assert "OH_CORNERS_VISUAL_ORDER_V28" in script
    assert 'leftGroup-rightGroup||(left.side==="over"?left.line-right.line:right.line-left.line)' in script
    assert "OH_TOP_PICK_SCORE_V28" in script
    assert "OH_FINAL_PICK_RESULTS_V28" in script
    assert "probability_at_recommendation" in script
    assert "odds_at_recommendation" in script
    assert "ev_at_recommendation" in script
    assert "Resultados de los picks recomendados" in script
    assert ".oh-final-pick-results" in styles
    assert workflow.count("OH_TOP_PICK_SCORE_V28") >= 2
    assert workflow.count("OH_FINAL_PICK_RESULTS_V28") >= 2
    assert workflow.count("OH_CORNERS_VISUAL_ORDER_V28") >= 2


def test_v31_shows_corner_5_5_and_separates_probability_from_ev():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(encoding="utf-8")
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(encoding="utf-8")
    assert "OH_COMPLETE_FIXTURES_RESULTS_V29" in script
    assert "OH_CORNERS_55_VISIBLE_V31" in script
    assert '.filter(key=>!/^corners_(?:over|under)_5_5$/.test(key))' not in script
    assert '"corners_over_5_5","corners_under_5_5"' not in script
    assert '"cards_over_0_5","cards_under_0_5"' in script
    assert 'rawEv==null?NaN:Number(rawEv)' in script
    assert 'function ohProbabilityClass(value)' in script
    assert '.oh-probability-high' in styles
    assert 'data-final-results-tab="recommended"' in script
    assert 'data-final-results-tab="high"' in script
    assert "Resultados de los picks de mayor probabilidad" in script
    assert "Probabilidad ≥ 60% (sin importar EV ni cuota)" in script


def test_vercel_backend_ships_asian_engine_inside_backend_package():
    patcher = (ROOT / "vercel_backend_data_patch.py").read_text(encoding="utf-8")
    engine = (ROOT / "odds_value_engine.py").read_text(encoding="utf-8")

    assert '(path.parent / "asian_total_ev.py").write_text' in patcher
    assert '(path.parent / "asian_lines.py").write_text' in patcher
    assert "from .asian_total_ev import" in engine
    assert "from .asian_lines import" in engine


def test_picks_tab_is_inserted_and_verified_in_deployment():
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(encoding="utf-8")
    styles = (ROOT / "vercel_assets" / "match_summary_v2.css").read_text(encoding="utf-8")
    recovery = (ROOT / "vercel_source_recover.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "oddshunter-vercel-frontend-v1.yml").read_text(encoding="utf-8")

    assert "OH_VALUE_PICKS_V23" in script
    assert "OH_VALUE_PICKS_V23" in styles
    assert 'data-tab="picks"' in recovery
    assert workflow.count("OH_VALUE_PICKS_V23") >= 4
