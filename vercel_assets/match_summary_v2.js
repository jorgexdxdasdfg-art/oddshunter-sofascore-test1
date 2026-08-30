/* OH_MATCH_BALL_SIZE_V9 */

const ohOriginalSetHeaderExactV3=setHeader;
setHeader=function(view){
  ohOriginalSetHeaderExactV3(view);
  document.documentElement.classList.toggle("match-reference-light",view==="match");
};

summaryIcon = function(kind){
  if(kind==="ball"||kind==="ball-premium"){
    return `<span class="oh-ball-3d" aria-hidden="true">⚽</span>`;
  }
  if(kind==="corner")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohFlagV7Shadow" x="-30%" y="-25%" width="160%" height="170%"><feDropShadow dx="0" dy="1.35" stdDeviation="1.05" flood-color="#111827" flood-opacity=".36"/></filter><linearGradient id="ohFlagV7Pole" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#555a61"/><stop offset=".35" stop-color="#f2f3f4"/><stop offset=".65" stop-color="#a3a7ad"/><stop offset="1" stop-color="#45494f"/></linearGradient><linearGradient id="ohFlagV7Red" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ff5b65"/><stop offset=".45" stop-color="#ec1f31"/><stop offset="1" stop-color="#a50014"/></linearGradient></defs><g filter="url(#ohFlagV7Shadow)"><ellipse cx="9.7" cy="27" rx="5.1" ry="1.25" fill="#4b5057" opacity=".68"/><rect x="8.5" y="4.6" width="2.4" height="21.9" rx="1.2" fill="url(#ohFlagV7Pole)"/><path d="M10.65 6.25 25.2 10.7 10.65 15.4Z" fill="url(#ohFlagV7Red)" stroke="#a70818" stroke-width=".55" stroke-linejoin="round"/><path d="m12.3 7.25 9.25 3.05" stroke="#fff" stroke-width=".95" stroke-linecap="round" stroke-opacity=".52"/></g></svg>`;
  if(kind==="card")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohCard3dShadow" x="-40%" y="-35%" width="180%" height="190%"><feDropShadow dx="0" dy="1.7" stdDeviation="1.3" flood-color="#111827" flood-opacity=".35"/></filter><linearGradient id="ohCard3dGold" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff16a"/><stop offset=".42" stop-color="#ffd52c"/><stop offset="1" stop-color="#e6a700"/></linearGradient></defs><g filter="url(#ohCard3dShadow)"><rect x="8.6" y="4.25" width="14.8" height="23.2" rx="2.55" fill="url(#ohCard3dGold)" stroke="#d09b00" stroke-width=".65"/><path d="M11.1 6.8h8.65" stroke="#fff" stroke-width="1.35" stroke-linecap="round" stroke-opacity=".72"/><circle cx="20.65" cy="24.85" r="1.05" fill="#7f5a00"/></g></svg>`;
  if(kind==="target")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohTargetV7Shadow" x="-25%" y="-25%" width="150%" height="165%"><feDropShadow dx="0" dy="1.45" stdDeviation="1.1" flood-color="#111827" flood-opacity=".4"/></filter><radialGradient id="ohTargetV7Rim" cx="32%" cy="24%" r="78%"><stop stop-color="#fff"/><stop offset=".48" stop-color="#dfe1e4"/><stop offset="1" stop-color="#555b63"/></radialGradient><radialGradient id="ohTargetV7Red" cx="35%" cy="28%" r="75%"><stop stop-color="#ff6b72"/><stop offset=".5" stop-color="#ed1c2e"/><stop offset="1" stop-color="#9d0011"/></radialGradient></defs><g filter="url(#ohTargetV7Shadow)"><circle cx="16" cy="15.5" r="11.2" fill="url(#ohTargetV7Rim)"/><circle cx="16" cy="15.5" r="8.9" fill="#16181b"/><circle cx="16" cy="15.5" r="7.25" fill="url(#ohTargetV7Red)"/><circle cx="16" cy="15.5" r="4.85" fill="#fff"/><circle cx="16" cy="15.5" r="2.65" fill="#141518"/><path d="M9.1 8.5a9.6 9.6 0 0 1 6.4-2.6" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round" stroke-opacity=".55"/></g></svg>`;
  if(kind==="shield")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohShield3dShadow" x="-40%" y="-35%" width="185%" height="190%"><feDropShadow dx="0" dy="1.6" stdDeviation="1.35" flood-color="#111827" flood-opacity=".38"/></filter><linearGradient id="ohShield3dFace" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#9297a1"/><stop offset=".42" stop-color="#5f646e"/><stop offset="1" stop-color="#30343b"/></linearGradient></defs><g filter="url(#ohShield3dShadow)"><path d="M16 3.8 26 7.5v7.35c0 6.35-3.95 10.75-10 13.35-6.05-2.6-10-7-10-13.35V7.5Z" fill="url(#ohShield3dFace)" stroke="#444952" stroke-width=".65"/><path d="M8.4 9.05 16 6.3l7.6 2.75" fill="none" stroke="#fff" stroke-width="1.15" stroke-linecap="round" stroke-opacity=".45"/><path d="m16 10.1 1.65 3.35 3.7.54-2.67 2.6.63 3.67L16 18.52l-3.31 1.74.63-3.67-2.67-2.6 3.7-.54Z" fill="#fff"/></g></svg>`;
  return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohChart3dShadow" x="-35%" y="-35%" width="180%" height="190%"><feDropShadow dx="0" dy="1.55" stdDeviation="1.25" flood-color="#111827" flood-opacity=".34"/></filter><linearGradient id="ohChart3dPanel" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ffffff"/><stop offset=".58" stop-color="#e7e9ec"/><stop offset="1" stop-color="#b9bdc3"/></linearGradient><linearGradient id="ohChart3dRed" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#a90013"/><stop offset="1" stop-color="#f33b46"/></linearGradient></defs><g filter="url(#ohChart3dShadow)"><rect x="4.4" y="4.4" width="23.2" height="23.2" rx="3.1" fill="url(#ohChart3dPanel)"/><path d="M8.2 9.1v14.7h16.1" fill="none" stroke="#4d535b" stroke-width="1.8" stroke-linecap="round"/><path d="m10.4 21 4.3-5.5 3.65 2.35 5.55-7.05" fill="none" stroke="url(#ohChart3dRed)" stroke-width="2.45" stroke-linecap="round" stroke-linejoin="round"/><path d="m21.15 10.8 3.35-.55-.42 3.37" fill="#ed1c2e"/><path d="M6.6 6.4h12.8" stroke="#fff" stroke-width="1.15" stroke-linecap="round" stroke-opacity=".7"/></g></svg>`;
};

summaryMetric = function(label,value,suffix="",lead="",icon="ball",tone="green"){
  return `<div class="summary-metric tone-${tone}">
    <div class="summary-metric-title"><span class="summary-metric-icon">${summaryIcon(icon)}</span><span>${esc(label)}</span></div>
    ${lead?`<span class="summary-lead">${esc(lead)}</span>`:""}
    <strong class="summary-primary-value">${val(value,suffix)}</strong>
    ${!lead&&["shots","target","xg"].includes(icon)?'<span class="summary-caption">Promedio</span>':""}
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
      ${summaryMetric("Goles (2.5)",s.goals_over_2_5,"%","Más","ball-premium","green")}
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
        ${ohExpectedMetric("xg","xG",s.xg_home,s.xg_away)}
        ${ohExpectedMetric("corner","Córners",homeHistory.corners,awayHistory.corners)}
        ${ohExpectedMetric("card","Amarillas",homeHistory.yellow_cards,awayHistory.yellow_cards)}
        ${ohExpectedMetric("target","Remates",s.shots_home,s.shots_away)}
      </div>
      <div class="one-x-two">
        <div class="one-x-title"><span>${summaryIcon("shield")}</span>Probabilidades 1X2</div>
        <div class="one-x-grid"><div><small>Local</small><strong class="home-prob">${val(pr.home_win,"%")}</strong></div><div><small>Empate</small><strong>${val(pr.draw,"%")}</strong></div><div><small>Visitante</small><strong>${val(pr.away_win,"%")}</strong></div></div>
      </div>
    </div>

    <div class="panel scorelines-panel"><h3>Marcadores más probables</h3><div class="scoreline-list">${scorelines.map(x=>{const pct=(Number(x.probability)||0)*100;return `<div class="scoreline"><div class="scoreline-fill" style="width:${Math.max(4,pct/maxScore*100)}%"></div><span>${x.home_goals} - ${x.away_goals}</span><strong>${val(Math.round(pct*10)/10,"%")}</strong></div>`}).join("")||'<span class="muted">N/D</span>'}</div></div>`;

  requestAnimationFrame(()=>drawSummaryExpectedChart($("summaryExpectedChart"),combinedHistorySeries("xg_for",10),combinedHistorySeries("goals_for",10)));
};
