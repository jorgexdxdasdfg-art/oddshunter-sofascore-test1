/* OH_MATCH_SUMMARY_REFERENCE_V2 */

summaryIcon = function(kind){
  const defs=`<defs><filter id="ohShadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity=".28"/></filter><linearGradient id="ohGold" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ffe66a"/><stop offset="1" stop-color="#f3b700"/></linearGradient><linearGradient id="ohRed" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ff4d58"/><stop offset="1" stop-color="#d80820"/></linearGradient></defs>`;
  if(kind==="ball")return `<svg viewBox="0 0 32 32" aria-hidden="true">${defs}<circle cx="16" cy="16" r="12.5" fill="#fff" stroke="#111" stroke-width="1.4" filter="url(#ohShadow)"/><path d="m16 9 4.2 3-1.6 5h-5.2l-1.6-5 4.2-3Zm-8.9 6.2 4.7-3.2m8.4 0 4.7 3.2M10 24l3.4-7m8.6 7-3.4-7m-8.6 7h12" fill="#111" stroke="#111" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
  if(kind==="corner")return `<svg viewBox="0 0 32 32" aria-hidden="true">${defs}<path d="M9 27V6" stroke="#4b5563" stroke-width="2.2" stroke-linecap="round"/><path d="M10 7c6-3 8 3 14 0v10c-6 3-8-3-14 0Z" fill="url(#ohRed)" filter="url(#ohShadow)"/><path d="M5 27h11" stroke="#4b5563" stroke-width="2" stroke-linecap="round"/></svg>`;
  if(kind==="card")return `<svg viewBox="0 0 32 32" aria-hidden="true">${defs}<rect x="9" y="5" width="14" height="22" rx="2.8" fill="url(#ohGold)" filter="url(#ohShadow)"/><path d="M12 8h8" stroke="#fff" stroke-opacity=".55" stroke-width="1.4" stroke-linecap="round"/></svg>`;
  if(kind==="target")return `<svg viewBox="0 0 32 32" aria-hidden="true">${defs}<circle cx="16" cy="16" r="12" fill="#fff" stroke="#111827" stroke-width="1.6" filter="url(#ohShadow)"/><circle cx="16" cy="16" r="7.5" fill="none" stroke="#111827" stroke-width="2"/><circle cx="16" cy="16" r="3.2" fill="url(#ohRed)"/><path d="M16 2v5M16 25v5M2 16h5M25 16h5" stroke="#111827" stroke-width="1.4" stroke-linecap="round"/></svg>`;
  return `<svg viewBox="0 0 32 32" aria-hidden="true">${defs}<path d="M5 26V7M5 26h22" fill="none" stroke="#111827" stroke-width="2" stroke-linecap="round"/><path d="m8 22 5-7 4 3 8-11" fill="none" stroke="url(#ohRed)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" filter="url(#ohShadow)"/><circle cx="8" cy="22" r="1.8" fill="#ed1c2e"/><circle cx="13" cy="15" r="1.8" fill="#ed1c2e"/><circle cx="17" cy="18" r="1.8" fill="#ed1c2e"/><circle cx="25" cy="7" r="1.8" fill="#ed1c2e"/></svg>`;
};

summaryMetric = function(label,value,suffix="",lead="",icon="ball",tone="green"){
  return `<div class="summary-metric tone-${tone}">
    <div class="summary-metric-title"><span class="summary-metric-icon">${summaryIcon(icon)}</span><span>${esc(label)}</span></div>
    ${lead?`<span class="summary-lead">${esc(lead)}</span>`:""}
    <strong class="summary-primary-value">${val(value,suffix)}</strong>
    ${!lead&&["shots","xg"].includes(icon)?'<span class="summary-caption">Promedio</span>':""}
  </div>`;
};

function ohExpectedMetric(icon,label,home,away){
  return `<div class="expected-value-card"><div class="expected-value-title"><span>${summaryIcon(icon)}</span><span>${esc(label)}</span></div><strong>${val(home)} - ${val(away)}</strong><small>Local · Visitante</small></div>`;
}

renderSummary = function(){
  const p=state.currentMatch,s=p.summary||{},pr=s.probabilities||{};
  const homeHistory=p.comparison?.home?.summary||{};
  const awayHistory=p.comparison?.away?.summary||{};
  const scorelines=(s.top_scorelines||[]).slice(0,5);
  const maxScore=Math.max(1,...scorelines.map(x=>Number(x.probability)||0));
  $("matchContent").innerHTML=`
    <div class="summary-metric-grid">
      ${summaryMetric("BTTS",s.btts_yes,"%","Sí","ball","green")}
      ${summaryMetric("Goles (2.5)",s.goals_over_2_5,"%","Más","ball","green")}
      ${summaryMetric("Corners (9.5)",s.corners_over_9_5,"%","Más","corner","green")}
      ${summaryMetric("Tarjetas (3.5)",s.cards_over_3_5,"%","Más","card","green")}
      ${summaryMetric("Remates",s.shots_total,"","","target","dark")}
      ${summaryMetric("xG (Total)",s.xg_total,"","","xg","dark")}
    </div>

    <div class="summary-chart-card">
      <div class="summary-card-head"><h3>Esperado vs sucedido</h3><button class="chart-expand" type="button" aria-label="Ampliar gráfica">↗</button></div>
      <div class="summary-chart-legend"><span><i class="legend-line red"></i>xG esperado</span><span><i class="legend-line dashed"></i>Goles</span></div>
      <canvas id="summaryExpectedChart"></canvas>
      <div class="summary-chart-note">Datos basados en los últimos 10 partidos disponibles</div>
    </div>

    <div class="panel expected-values-panel">
      <h3>Valores esperados</h3>
      <div class="expected-values-grid">
        ${ohExpectedMetric("ball","xG",s.xg_home,s.xg_away)}
        ${ohExpectedMetric("corner","Córners",homeHistory.corners,awayHistory.corners)}
        ${ohExpectedMetric("card","Amarillas",homeHistory.yellow_cards,awayHistory.yellow_cards)}
        ${ohExpectedMetric("target","Remates",s.shots_home,s.shots_away)}
      </div>
      <div class="one-x-two">
        <div class="one-x-title"><span>${summaryIcon("target")}</span>Probabilidades 1X2</div>
        <div class="one-x-grid"><div><small>Local</small><strong class="home-prob">${val(pr.home_win,"%")}</strong></div><div><small>Empate</small><strong>${val(pr.draw,"%")}</strong></div><div><small>Visitante</small><strong>${val(pr.away_win,"%")}</strong></div></div>
      </div>
    </div>

    <div class="panel scorelines-panel"><h3>Marcadores más probables</h3><div class="scoreline-list">${scorelines.map(x=>{const pct=(Number(x.probability)||0)*100;return `<div class="scoreline"><div class="scoreline-fill" style="width:${Math.max(4,pct/maxScore*100)}%"></div><span>${x.home_goals} - ${x.away_goals}</span><strong>${val(Math.round(pct*10)/10,"%")}</strong></div>`}).join("")||'<span class="muted">N/D</span>'}</div></div>`;

  requestAnimationFrame(()=>drawSummaryExpectedChart($("summaryExpectedChart"),combinedHistorySeries("xg_for",10),combinedHistorySeries("goals_for",10)));
};
