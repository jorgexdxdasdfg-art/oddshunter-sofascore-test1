/* OH_MATCH_SUMMARY_EXACT_V3 */

const ohOriginalSetHeaderExactV3=setHeader;
setHeader=function(view){
  ohOriginalSetHeaderExactV3(view);
  document.documentElement.classList.toggle("match-reference-light",view==="match");
};

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
  return `<div class="expected-value-card"><div class="expected-value-title"><span>${summaryIcon(icon)}</span><span>${esc(label)}</span></div><strong>${val(home)} - ${val(away)}</strong><small>Local - Visitante</small></div>`;
}

drawSummaryExpectedChart=function(canvas,xgHistory,goalHistory){
  if(!canvas)return;
  const dpr=window.devicePixelRatio||1,w=Math.max(300,canvas.clientWidth||320),h=210;
  canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
  const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const finite=a=>a.filter(Number.isFinite),average=a=>{const x=finite(a);return x.length?x.reduce((n,v)=>n+v,0)/x.length:null};
  const summary=state.currentMatch?.summary||{};
  const xgEnd=average(xgHistory)??(Number(summary.xg_total)||0);
  const goalEnd=average(goalHistory)??(Number(summary.expected_goals)||0);
  if(!xgEnd&&!goalEnd){ctx.fillStyle="#777";ctx.font='13px system-ui';ctx.textAlign="center";ctx.fillText("Sin datos históricos suficientes",w/2,h/2);return}
  const redWeights=[0,.05,.13,.29,.43,.55,.67,.78,.88,1];
  const blackWeights=[0,.03,.10,.19,.30,.41,.53,.66,.80,1];
  const red=redWeights.map(v=>v*xgEnd),black=blackWeights.map(v=>v*goalEnd);
  const left=34,right=48,top=14,bottom=31,innerW=w-left-right,innerH=h-top-bottom;
  const max=Math.max(3,Math.ceil(Math.max(...red,...black)*2)/2),xAt=i=>left+innerW*i/(red.length-1),yAt=v=>top+innerH-(v/max)*innerH;
  ctx.font='11px system-ui';ctx.textBaseline="middle";
  for(let i=0;i<=3;i++){const y=top+innerH*i/3;ctx.strokeStyle="#e5e5e7";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillStyle="#777";ctx.textAlign="right";ctx.fillText(visibleNumber(max*(1-i/3)),left-7,y)}
  const draw=(arr,color,dashed)=>{ctx.strokeStyle=color;ctx.lineWidth=2.2;ctx.lineCap="round";ctx.lineJoin="round";ctx.setLineDash(dashed?[6,5]:[]);ctx.beginPath();arr.forEach((v,i)=>i?ctx.lineTo(xAt(i),yAt(v)):ctx.moveTo(xAt(i),yAt(v)));ctx.stroke();ctx.setLineDash([]);if(!dashed){ctx.fillStyle=color;arr.forEach((v,i)=>{ctx.beginPath();ctx.arc(xAt(i),yAt(v),2.2,0,Math.PI*2);ctx.fill()})}};
  draw(red,"#ed1c2e",false);draw(black,"#111",true);
  ctx.fillStyle="#777";ctx.textAlign="center";ctx.textBaseline="top";[0,15,30,45,60,75,90].forEach((m,i)=>ctx.fillText(`${m}'`,left+innerW*i/6,h-bottom+9));
  ctx.font='800 14px system-ui';ctx.textAlign="left";ctx.textBaseline="middle";ctx.fillStyle="#ed1c2e";ctx.fillText(visibleNumber(xgEnd),w-right+8,yAt(xgEnd));ctx.fillStyle="#111";ctx.fillText(visibleNumber(goalEnd),w-right+8,yAt(goalEnd));
};

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
