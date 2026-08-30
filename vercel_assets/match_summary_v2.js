/* OH_MATCH_REFINEMENTS_V6 */

const ohOriginalSetHeaderExactV3=setHeader;
setHeader=function(view){
  ohOriginalSetHeaderExactV3(view);
  document.documentElement.classList.toggle("match-reference-light",view==="match");
};

summaryIcon = function(kind){
  const emojiIcons={ball:"⚽","ball-premium":"⚽",corner:"🚩",target:"🎯"};
  if(emojiIcons[kind])return `<span class="oh-summary-emoji oh-summary-emoji-${kind}" aria-hidden="true">${emojiIcons[kind]}</span>`;
  if(kind==="ball"||kind==="ball-premium"){
    const id=kind==="ball-premium"?"ohBallPremium3d":"ohBall3d";
    const rim=kind==="ball-premium"?"#777b82":"#8d9095";
    return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="${id}Shadow" x="-35%" y="-35%" width="170%" height="180%"><feDropShadow dx="0" dy="1.6" stdDeviation="1.35" flood-color="#111827" flood-opacity=".34"/></filter><radialGradient id="${id}Sphere" cx="31%" cy="22%" r="76%"><stop stop-color="#ffffff"/><stop offset=".48" stop-color="#f6f7f8"/><stop offset=".78" stop-color="#d9dce0"/><stop offset="1" stop-color="#969ba2"/></radialGradient><linearGradient id="${id}Panel" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#3f4349"/><stop offset=".48" stop-color="#111214"/><stop offset="1" stop-color="#000000"/></linearGradient></defs><g filter="url(#${id}Shadow)"><circle cx="16" cy="15.6" r="12.15" fill="url(#${id}Sphere)" stroke="${rim}" stroke-width=".72"/><path d="m16 9.35 4.05 2.92-1.55 4.77h-5l-1.55-4.77L16 9.35Z" fill="url(#${id}Panel)"/><path d="m11.95 12.27-4.7 2.68.7 5.25 3.95 3.55 2.15-6.71m5.9-4.77 4.7 2.68-.7 5.25-3.95 3.55-2.05-6.71M7.95 20.2l-1.1 1.28M24.05 20.2l1.1 1.28M11.9 23.75l.45 2.2M20 23.75l-.4 2.2" fill="none" stroke="#34373c" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.2 8.8a10.5 10.5 0 0 1 7.9-4.2" fill="none" stroke="#fff" stroke-width="1.35" stroke-linecap="round" stroke-opacity=".78"/></g></svg>`;
  }
  if(kind==="corner")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohFlag3dShadow" x="-35%" y="-35%" width="180%" height="190%"><feDropShadow dx="0" dy="1.5" stdDeviation="1.2" flood-color="#111827" flood-opacity=".34"/></filter><linearGradient id="ohFlag3dPole" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#5d6269"/><stop offset=".35" stop-color="#f0f2f4"/><stop offset=".62" stop-color="#9ca1a8"/><stop offset="1" stop-color="#4a4e54"/></linearGradient><linearGradient id="ohFlag3dRed" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ff6b70"/><stop offset=".4" stop-color="#f52c37"/><stop offset="1" stop-color="#a90013"/></linearGradient></defs><g filter="url(#ohFlag3dShadow)"><ellipse cx="10.2" cy="27.3" rx="6.2" ry="1.45" fill="#5d6269" opacity=".62"/><rect x="8.65" y="4.4" width="2.6" height="22.4" rx="1.3" fill="url(#ohFlag3dPole)"/><path d="M11.15 6.1c5.15-2.35 8.55 2.75 14.05.15v10.2c-5.5 2.6-8.9-2.5-14.05-.15Z" fill="url(#ohFlag3dRed)" stroke="#b70b1d" stroke-width=".55"/><path d="M12.6 7.1c3.8-1.25 7 2.45 10.95.55" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round" stroke-opacity=".58"/></g></svg>`;
  if(kind==="card")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohCard3dShadow" x="-40%" y="-35%" width="180%" height="190%"><feDropShadow dx="0" dy="1.7" stdDeviation="1.3" flood-color="#111827" flood-opacity=".35"/></filter><linearGradient id="ohCard3dGold" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff16a"/><stop offset=".42" stop-color="#ffd52c"/><stop offset="1" stop-color="#e6a700"/></linearGradient></defs><g filter="url(#ohCard3dShadow)"><rect x="8.6" y="4.25" width="14.8" height="23.2" rx="2.55" fill="url(#ohCard3dGold)" stroke="#d09b00" stroke-width=".65"/><path d="M11.1 6.8h8.65" stroke="#fff" stroke-width="1.35" stroke-linecap="round" stroke-opacity=".72"/><circle cx="20.65" cy="24.85" r="1.05" fill="#7f5a00"/></g></svg>`;
  if(kind==="target")return `<svg viewBox="0 0 32 32" aria-hidden="true"><defs><filter id="ohTarget3dShadow" x="-40%" y="-40%" width="190%" height="195%"><feDropShadow dx="0" dy="1.65" stdDeviation="1.3" flood-color="#111827" flood-opacity=".38"/></filter><radialGradient id="ohTarget3dRim" cx="30%" cy="22%" r="80%"><stop stop-color="#ffffff"/><stop offset=".55" stop-color="#d9dde1"/><stop offset="1" stop-color="#747a82"/></radialGradient><radialGradient id="ohTarget3dRed" cx="34%" cy="28%" r="75%"><stop stop-color="#ff6d70"/><stop offset=".52" stop-color="#ed1c2e"/><stop offset="1" stop-color="#a60011"/></radialGradient></defs><g filter="url(#ohTarget3dShadow)"><circle cx="14.7" cy="17" r="10.9" fill="url(#ohTarget3dRim)"/><circle cx="14.7" cy="17" r="8.7" fill="#fff" stroke="#626870" stroke-width=".45"/><circle cx="14.7" cy="17" r="6.35" fill="url(#ohTarget3dRed)"/><circle cx="14.7" cy="17" r="3.85" fill="#fff"/><circle cx="14.7" cy="17" r="1.75" fill="#f1b719"/><path d="m15.1 16.6 9.45-9.45" stroke="#32363b" stroke-width="1.45" stroke-linecap="round"/><path d="M22.4 5.2v4.05h4.05" fill="#ff3946" stroke="#b50818" stroke-width=".55" stroke-linejoin="round"/></g></svg>`;
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
