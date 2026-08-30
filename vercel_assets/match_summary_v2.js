/* OH_MATCH_SUMMARY_FIXES_V11 */

const ohOriginalSetHeaderExactV3=setHeader;
setHeader=function(view){
  ohOriginalSetHeaderExactV3(view);
  document.documentElement.classList.toggle("match-reference-light",view==="match");
};

summaryIcon = function(kind){
  if(kind==="ball"||kind==="ball-premium"){
    return `<img class="oh-ball-3d" src="/assets/icons/ball-3d-v10.png" alt="" aria-hidden="true" decoding="async">`;
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
  ctx.font='800 14px system-ui';ctx.textAlign="left";ctx.textBaseline="middle";
  const redNaturalY=yAt(xgEnd),blackNaturalY=yAt(goalEnd),labelGap=22;
  let redLabelY=redNaturalY,blackLabelY=blackNaturalY;
  const minLabelY=top+8,maxLabelY=top+innerH-8;
  if(Math.abs(redLabelY-blackLabelY)<labelGap){
    const middle=(redLabelY+blackLabelY)/2;
    const upper=Math.max(minLabelY,Math.min(maxLabelY-labelGap,middle-labelGap/2));
    const lower=upper+labelGap;
    if(redNaturalY<=blackNaturalY){redLabelY=upper;blackLabelY=lower}
    else{blackLabelY=upper;redLabelY=lower}
  }
  const clampLabel=y=>Math.max(minLabelY,Math.min(maxLabelY,y));
  ctx.fillStyle="#ed1c2e";ctx.fillText(visibleNumber(xgEnd),w-right+8,clampLabel(redLabelY));
  ctx.fillStyle="#111";ctx.fillText(visibleNumber(goalEnd),w-right+8,clampLabel(blackLabelY));
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

function ohComparisonLabel(label){
  return String(label||"")==="BTTS"?"Ambos marcan":String(label||"");
}

function ohComparisonValue(value,kind){
  return value===null||value===undefined?"N/D":kind==="percent"?`${visibleNumber(value)}%`:visibleNumber(value);
}

renderComparison = function(){
  const p=state.currentMatch,c=p.comparison||{},rows=c.rows||[];
  const homeName=p.event.home_team,awayName=p.event.away_team;
  const joint=rows.filter(row=>row.kind==="percent"&&row.home!==null&&row.away!==null).map(row=>({
    label:String(row.label||"")==="BTTS"?"BTTS":String(row.label||""),
    value:Math.round((Number(row.home)+Number(row.away))/2*10)/10
  }));
  $("matchContent").innerHTML=`<div class="oh-comparison-reference">
    <section class="panel oh-last-matches-panel">
      <h3>Últimos partidos</h3>
      <table class="oh-last-matches-table">
        <thead><tr><th>${esc(homeName)}</th><th>Métrica</th><th>${esc(awayName)}</th></tr></thead>
        <tbody>${rows.map(row=>`<tr title="${esc(row.note||"")}"><td>${ohComparisonValue(row.home,row.kind)}</td><td>${esc(ohComparisonLabel(row.label))}</td><td>${ohComparisonValue(row.away,row.kind)}</td></tr>`).join("")}</tbody>
      </table>
    </section>
    <section class="panel oh-joint-panel">
      <h3>Tendencia conjunta</h3>
      <div class="oh-joint-list">${joint.map(item=>`<div class="oh-joint-row"><span>${esc(item.label)}</span><div class="oh-joint-track"><i style="width:${Math.max(0,Math.min(100,item.value))}%"></i></div><strong>${visibleNumber(item.value)}%</strong></div>`).join("")||'<p class="muted">Sin métricas conjuntas suficientes.</p>'}</div>
    </section>
  </div>`;
};

function ohTrendSeries(side,key){
  return seriesFrom(side,key).slice(-10);
}

function ohTrendAverage(values){
  const finite=values.filter(Number.isFinite);
  return finite.length?finite.reduce((sum,value)=>sum+value,0)/finite.length:null;
}

function ohTrendRollingAverage(values,windowSize=3){
  return values.map((value,index)=>{
    if(!Number.isFinite(value))return null;
    const window=values.slice(Math.max(0,index-windowSize+1),index+1).filter(Number.isFinite);
    return window.length?window.reduce((sum,item)=>sum+item,0)/window.length:null;
  });
}

function ohTrendPercentage(side,predicate){
  const scored=ohTrendSeries(side,"goals_for");
  const received=ohTrendSeries(side,"goals_against");
  let hits=0,total=0;
  for(let index=0;index<Math.max(scored.length,received.length);index++){
    if(!Number.isFinite(scored[index])||!Number.isFinite(received[index]))continue;
    total++;
    if(predicate(scored[index],received[index]))hits++;
  }
  return total?Math.round(hits/total*100):null;
}

function ohTrendRollingBtts(side){
  const scored=ohTrendSeries(side,"goals_for");
  const received=ohTrendSeries(side,"goals_against");
  const result=[];
  let hits=0,total=0;
  for(let index=0;index<Math.max(scored.length,received.length);index++){
    if(!Number.isFinite(scored[index])||!Number.isFinite(received[index])){
      result.push(null);
      continue;
    }
    total++;
    if(scored[index]>0&&received[index]>0)hits++;
    result.push(Math.round(hits/total*100));
  }
  return result;
}

function ohTrendLegend(homeName,awayName){
  return `<div class="oh-trend-legend"><span><i class="home"></i>${esc(homeName)}</span><span><i class="away"></i>${esc(awayName)}</span></div>`;
}

function ohTrendInfo(){
  return `<span class="oh-trend-info" aria-hidden="true">${infoSvg()}</span>`;
}

function ohTrendCard(title,canvasId,homeName,awayName){
  return `<section class="oh-trend-card oh-trend-line-card">
    <div class="oh-trend-title"><div><h3>${esc(title)}</h3><small>Promedio móvil · 3 partidos</small></div>${ohTrendInfo()}</div>
    ${ohTrendLegend(homeName,awayName)}
    <canvas class="oh-trend-line-canvas" id="${canvasId}"></canvas>
  </section>`;
}

function ohDrawTrendLine(canvas,homeValues,awayValues,homeFinalAverage=null,awayFinalAverage=null){
  if(!canvas)return;
  const dpr=window.devicePixelRatio||1;
  const width=Math.max(280,canvas.clientWidth||320),height=118;
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  const ctx=canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const count=Math.max(homeValues.length,awayValues.length);
  const finite=[...homeValues,...awayValues].filter(Number.isFinite);
  if(!count||!finite.length){
    ctx.fillStyle="#7a7a80";ctx.font="12px system-ui";ctx.textAlign="center";
    ctx.fillText("Sin datos históricos suficientes",width/2,height/2);return;
  }
  const left=27,right=44,top=5,bottom=22;
  const innerWidth=width-left-right,innerHeight=height-top-bottom;
  const maxValue=Math.max(3,Math.ceil(Math.max(...finite)));
  const xAt=index=>left+innerWidth*(count<=1?0:index/(count-1));
  const yAt=value=>top+innerHeight-(Math.max(0,Math.min(maxValue,value))/maxValue)*innerHeight;
  ctx.font="9px system-ui";ctx.textBaseline="middle";
  for(let value=0;value<=maxValue;value++){
    const y=yAt(value);
    ctx.strokeStyle="#e3e3e6";ctx.lineWidth=1;ctx.setLineDash(value? [3,3]:[]);
    ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle="#6f7076";ctx.textAlign="right";ctx.fillText(value.toFixed(1),left-7,y);
  }
  const draw=(values,color)=>{
    ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.9;ctx.lineCap="round";ctx.lineJoin="round";
    ctx.beginPath();let started=false;
    values.forEach((value,index)=>{
      if(!Number.isFinite(value)){started=false;return}
      const x=xAt(index),y=yAt(value);
      if(!started){ctx.moveTo(x,y);started=true}else ctx.lineTo(x,y);
    });
    ctx.stroke();
    values.forEach((value,index)=>{
      if(!Number.isFinite(value))return;
      ctx.beginPath();ctx.arc(xAt(index),yAt(value),2,0,Math.PI*2);ctx.fill();
    });
  };
  draw(homeValues,"#d62c31");draw(awayValues,"#242529");
  ctx.fillStyle="#77787e";ctx.font="9px system-ui";ctx.textAlign="center";ctx.textBaseline="top";
  for(let index=0;index<count;index++)ctx.fillText(String(index+1),xAt(index),height-bottom+6);
  const homeAverage=Number.isFinite(homeFinalAverage)?homeFinalAverage:ohTrendAverage(homeValues);
  const awayAverage=Number.isFinite(awayFinalAverage)?awayFinalAverage:ohTrendAverage(awayValues);
  if(homeAverage===null&&awayAverage===null)return;
  const labelX=width-1,minY=top+7,maxY=top+innerHeight-7,gap=17;
  let homeY=homeAverage===null?null:yAt(homeAverage),awayY=awayAverage===null?null:yAt(awayAverage);
  if(homeY!==null&&awayY!==null&&Math.abs(homeY-awayY)<gap){
    const middle=(homeY+awayY)/2,upper=Math.max(minY,Math.min(maxY-gap,middle-gap/2));
    if(homeY<=awayY){homeY=upper;awayY=upper+gap}else{awayY=upper;homeY=upper+gap}
  }
  ctx.font="800 13px system-ui";ctx.textAlign="right";ctx.textBaseline="middle";
  if(homeY!==null){ctx.fillStyle="#d62c31";ctx.fillText(homeAverage.toFixed(2),labelX,Math.max(minY,Math.min(maxY,homeY)))}
  if(awayY!==null){ctx.fillStyle="#17181b";ctx.fillText(awayAverage.toFixed(2),labelX,Math.max(minY,Math.min(maxY,awayY)))}
}

function ohDrawTrendBtts(canvas,homeValues,awayValues){
  if(!canvas)return;
  const dpr=window.devicePixelRatio||1;
  const width=Math.max(240,canvas.clientWidth||300),height=70;
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const count=Math.max(homeValues.length,awayValues.length);
  if(!count){ctx.fillStyle="#777";ctx.font="12px system-ui";ctx.textAlign="center";ctx.fillText("Sin datos",width/2,height/2);return}
  const left=7,right=43,top=2,bottom=18,innerWidth=width-left-right,innerHeight=height-top-bottom;
  const slot=innerWidth/count,barWidth=Math.max(4,Math.min(9,slot*.27));
  const drawBar=(index,value,offset,color)=>{
    if(!Number.isFinite(value))return;
    const barHeight=Math.max(3,innerHeight*Math.max(0,Math.min(100,value))/100);
    const x=left+slot*index+slot/2+offset-barWidth/2;
    ctx.fillStyle=color;ctx.fillRect(x,top+innerHeight-barHeight,barWidth,barHeight);
  };
  for(let index=0;index<count;index++){
    drawBar(index,homeValues[index],-barWidth*.62,"#d62c31");
    drawBar(index,awayValues[index],barWidth*.62,"#242529");
  }
  ctx.strokeStyle="#e3e3e6";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,top+innerHeight+.5);ctx.lineTo(width-right,top+innerHeight+.5);ctx.stroke();
  ctx.fillStyle="#77787e";ctx.font="9px system-ui";ctx.textAlign="center";ctx.textBaseline="top";
  for(let index=0;index<count;index++)ctx.fillText(String(index+1),left+slot*index+slot/2,height-bottom+5);
}

const ohOriginalRenderMatchTabTrendsV12=renderMatchTab;
renderMatchTab=function(){
  $("matchHeader")?.classList.toggle("hidden",state.currentMatchTab==="trends");
  ohOriginalRenderMatchTabTrendsV12();
};

renderTrends = function(){
  const p=state.currentMatch,e=p?.event||{};
  const homeName=e.home_team||"Local",awayName=e.away_team||"Visitante";
  const homeGoals=ohTrendSeries("home","goals_for"),awayGoals=ohTrendSeries("away","goals_for");
  const homeAgainst=ohTrendSeries("home","goals_against"),awayAgainst=ohTrendSeries("away","goals_against");
  const homeOver=ohTrendPercentage("home",(scored,received)=>scored+received>1.5);
  const awayOver=ohTrendPercentage("away",(scored,received)=>scored+received>1.5);
  const homeBtts=ohTrendPercentage("home",(scored,received)=>scored>0&&received>0);
  const awayBtts=ohTrendPercentage("away",(scored,received)=>scored>0&&received>0);
  $("matchContent").innerHTML=`<div class="oh-trends-reference">
    <section class="oh-trend-teams">
      <div class="oh-trend-team home">${crest(e.home_team_id,homeName)}<strong>${esc(homeName)}</strong></div>
      <span class="oh-trend-vs">VS</span>
      <div class="oh-trend-team away"><strong>${esc(awayName)}</strong>${crest(e.away_team_id,awayName)}</div>
    </section>
    ${ohTrendCard("Goles por partido","ohTrendGoals",homeName,awayName)}
    ${ohTrendCard("Goles recibidos por partido","ohTrendAgainst",homeName,awayName)}
    <section class="oh-trend-card oh-trend-progress-card">
      <div class="oh-trend-title"><div><h3>+1.5 goles</h3><small>Porcentaje de partidos</small></div>${ohTrendInfo()}</div>
      ${ohTrendLegend(homeName,awayName)}
      <div class="oh-trend-progress-row"><div class="oh-trend-track"><i class="home" style="width:${homeOver??0}%"></i></div><strong class="home">${homeOver===null?"N/D":`${homeOver}%`}</strong></div>
      <div class="oh-trend-progress-row"><div class="oh-trend-track"><i class="away" style="width:${awayOver??0}%"></i></div><strong>${awayOver===null?"N/D":`${awayOver}%`}</strong></div>
    </section>
    <section class="oh-trend-card oh-trend-btts-card">
      <div class="oh-trend-title"><div><h3>Ambos marcan (BTTS)</h3><small>Porcentaje de partidos</small></div>${ohTrendInfo()}</div>
      ${ohTrendLegend(homeName,awayName)}
      <div class="oh-trend-btts-body"><canvas id="ohTrendBtts"></canvas><div class="oh-trend-btts-values"><strong class="home">${homeBtts===null?"N/D":`${homeBtts}%`}</strong><strong>${awayBtts===null?"N/D":`${awayBtts}%`}</strong></div></div>
    </section>
  </div>`;
  requestAnimationFrame(()=>{
    ohDrawTrendLine($("ohTrendGoals"),ohTrendRollingAverage(homeGoals),ohTrendRollingAverage(awayGoals),ohTrendAverage(homeGoals),ohTrendAverage(awayGoals));
    ohDrawTrendLine($("ohTrendAgainst"),ohTrendRollingAverage(homeAgainst),ohTrendRollingAverage(awayAgainst),ohTrendAverage(homeAgainst),ohTrendAverage(awayAgainst));
    ohDrawTrendBtts($("ohTrendBtts"),ohTrendRollingBtts("home"),ohTrendRollingBtts("away"));
  });
};

function ohLiveNavSvg(){
  return `<svg class="nav-icon oh-nav-live" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" fill="currentColor"/><path d="M7.7 7.7a6.1 6.1 0 0 0 0 8.6M16.3 7.7a6.1 6.1 0 0 1 0 8.6M4.7 4.7a10.3 10.3 0 0 0 0 14.6M19.3 4.7a10.3 10.3 0 0 1 0 14.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
}

function ohCalendarNavSvg(){
  return `<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M7 3v4M17 3v4M3 9h18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
}

function ohInstallLiveNavigation(){
  const main=document.querySelector("main");
  const statsView=document.querySelector('[data-view="stats"]');
  if(main&&statsView&&!document.querySelector('[data-view="live"]')){
    const liveView=document.createElement("section");
    liveView.className="view";
    liveView.dataset.view="live";
    liveView.innerHTML=`<div class="screen-title oh-live-title"><h1><span class="oh-live-title-icon">${ohLiveNavSvg()}</span>Live</h1></div><div id="liveList" class="cards"></div>`;
    main.insertBefore(liveView,statsView);
  }
  const upcomingButton=document.querySelector('.bottom-nav [data-nav="upcoming"]');
  const favoritesButton=document.querySelector('.bottom-nav [data-nav="favorites"]');
  if(upcomingButton){
    upcomingButton.dataset.nav="live";
    upcomingButton.setAttribute("aria-label","Live");
    upcomingButton.innerHTML=`${ohLiveNavSvg()}<small>Live</small>`;
  }
  if(favoritesButton){
    favoritesButton.dataset.nav="upcoming";
    favoritesButton.setAttribute("aria-label","Próximos");
    favoritesButton.innerHTML=`${ohCalendarNavSvg()}<small>Próximos</small>`;
  }
}

function ohRenderLiveList(){
  if(!$("liveList"))return;
  const selected=state.selectedLeague;
  const live=uniqueMatches([...(state.dayEvents||[]),...(state.upcoming||[])])
    .filter(match=>isLiveStatus(match)&&(!selected||match.competition_key===selected));
  putCards("liveList",live,"No hay partidos en vivo ahora.");
}

function ohRenderHomeWithoutLive(){
  if(!$("featuredList"))return;
  const day=filteredDay().filter(match=>!isLiveStatus(match));
  const dayName=state.dayOffset<0?"ayer":state.dayOffset>0?"mañana":"hoy";
  putDayCards("featuredList",day,`No hay partidos de ${dayName} para este filtro.`);
}

ohInstallLiveNavigation();
const ohOriginalRenderAllListsLiveV13=renderAllLists;
renderAllLists=function(){
  ohOriginalRenderAllListsLiveV13();
  ohRenderHomeWithoutLive();
  ohRenderLiveList();
};
ohRenderLiveList();

let ohLineupTab="starters";

function ohLineupSot(player){
  const value=Number(player?.avg_shots_on_target);
  return Number.isFinite(value)?value:null;
}

function ohShortPlayerName(name){
  const parts=String(name||"Jugador").trim().split(/\s+/).filter(Boolean);
  if(parts.length<2)return parts[0]||"Jugador";
  return `${parts[0].charAt(0)}. ${parts.at(-1)}`;
}

function ohJerseySvg(number){
  return `<svg viewBox="0 0 44 40" aria-hidden="true"><path d="M13 5 18 2h8l5 3 9 5-5 9-5-3v21H14V16l-5 3-5-9 9-5Z" fill="var(--shirt)" stroke="rgba(0,0,0,.28)" stroke-width="1.2" stroke-linejoin="round"/><path d="M18 2c.5 3 7.5 3 8 0" fill="none" stroke="rgba(255,255,255,.38)" stroke-width="1.4"/><text x="22" y="24" text-anchor="middle" fill="var(--shirt-ink)" font-size="10" font-weight="900">${esc(number??"—")}</text></svg>`;
}

function ohPitchPlayer(player){
  const sot=ohLineupSot(player);
  return `<div class="oh-pitch-player" title="${esc(player?.name||"Jugador")}">
    <span class="oh-player-jersey">${ohJerseySvg(player?.shirt_number)}</span>
    <strong>${esc(ohShortPlayerName(player?.name))}</strong>
    <small>${sot===null?"N/D":sot.toFixed(1)} a puerta</small>
  </div>`;
}

function ohFormationRows(side){
  const starters=Array.isArray(side?.starters)?side.starters:[];
  if(!starters.length)return [];
  const keeper=starters.find(player=>String(player?.position||"").toUpperCase()==="G")||starters[0];
  const outfield=starters.filter(player=>player!==keeper);
  const counts=String(side?.formation||"").match(/\d+/g)?.map(Number).filter(value=>value>0)||[];
  if(counts.length&&counts.reduce((sum,value)=>sum+value,0)===outfield.length){
    const rows=[];
    let cursor=0;
    counts.forEach(count=>{rows.push(outfield.slice(cursor,cursor+count));cursor+=count});
    return [...rows.reverse(),[keeper]];
  }
  const forwards=outfield.filter(player=>String(player?.position||"").toUpperCase()==="F");
  const midfield=outfield.filter(player=>String(player?.position||"").toUpperCase()==="M");
  const defense=outfield.filter(player=>String(player?.position||"").toUpperCase()==="D");
  const unplaced=outfield.filter(player=>!["F","M","D"].includes(String(player?.position||"").toUpperCase()));
  return [forwards,midfield,[...defense,...unplaced],[keeper]].filter(row=>row.length);
}

function ohPitchTeam(side,teamName,sideKey){
  const rows=ohFormationRows(side);
  return `<section class="oh-pitch-team ${sideKey}" style="--rows:${Math.max(1,rows.length)}">
    <div class="oh-pitch-team-name"><strong>${esc(teamName)}</strong><span>•</span><b>${esc(side?.formation||"N/D")}</b></div>
    <div class="oh-pitch-lineup">${rows.map(row=>`<div class="oh-pitch-row" style="--players:${row.length}">${row.map(ohPitchPlayer).join("")}</div>`).join("")}</div>
  </section>`;
}

function ohLineupListPlayer(player){
  const sot=ohLineupSot(player);
  return `<li><span class="oh-list-shirt">${esc(player?.shirt_number??"—")}</span><span><strong>${esc(player?.name||"Jugador")}</strong><small>${esc(player?.position||"")}</small></span><b>${sot===null?"N/D":sot.toFixed(2)} a puerta</b></li>`;
}

function ohLineupList(title,players,teamName,sideKey){
  const rows=Array.isArray(players)?players:[];
  return `<section class="panel oh-lineup-list-panel ${sideKey}"><h3>${esc(teamName)}</h3><h4>${esc(title)} · ${rows.length}</h4>${rows.length?`<ul>${rows.map(ohLineupListPlayer).join("")}</ul>`:'<p class="muted">Sin datos guardados.</p>'}</section>`;
}

function ohTeamSotAverage(side){
  const values=(Array.isArray(side?.starters)?side.starters:[]).map(ohLineupSot).filter(Number.isFinite);
  return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null;
}

function ohLineupSummary(data,event){
  const home=ohTeamSotAverage(data.home),away=ohTeamSotAverage(data.away);
  return `<section class="panel oh-lineup-summary"><h3>Promedio de remates a puerta por jugador</h3><p>Valor promedio por partido basado en hasta los últimos 10 encuentros disponibles.</p><div class="oh-lineup-summary-grid">
    <div class="home"><span><i></i>${esc(event.home_team||"Local")}</span><strong>${home===null?"N/D":home.toFixed(2)} a puerta</strong></div>
    <div class="away"><span><i></i>${esc(event.away_team||"Visitante")}</span><strong>${away===null?"N/D":away.toFixed(2)} a puerta</strong></div>
  </div><footer><span>${infoSvg()}</span> Estadística mostrada: <strong>remates a puerta (solo)</strong></footer></section>`;
}

function ohLineupPanelMarkup(){
  const p=state.currentMatch||{},event=p.event||{},data=p.lineups?.data||{};
  if(ohLineupTab==="substitutes")return `<div class="oh-lineup-lists">${ohLineupList("Suplentes",data.home?.substitutes,event.home_team||"Local","home")}${ohLineupList("Suplentes",data.away?.substitutes,event.away_team||"Visitante","away")}</div>`;
  if(ohLineupTab==="absences")return `<div class="lineup-placeholder oh-absence-placeholder"><div><h3>Bajas todavía no guardadas</h3><p>OddsHunter no mostrará lesiones o sanciones hasta tenerlas guardadas para este partido.</p></div></div>`;
  return `<div class="oh-lineup-pitch" id="ohLineupPitch">
    <div class="oh-field-lines"><i></i></div>
    ${ohPitchTeam(data.home,event.home_team||"Local","home")}
    ${ohPitchTeam(data.away,event.away_team||"Visitante","away")}
  </div>${ohLineupSummary(data,event)}`;
}

function ohFallbackTeamColor(teamId){
  const palette=["#c62828","#1565c0","#6a1b9a","#ef6c00","#00897b","#2e7d32","#263238","#ad1457"];
  return palette[Math.abs(Number(teamId)||0)%palette.length];
}

function ohInkForColor([red,green,blue]){
  return (red*299+green*587+blue*114)/1000>155?"#101014":"#fff";
}

function ohExtractCrestColor(teamId,sideKey){
  const shell=document.querySelector(".oh-lineups-shell");
  if(!shell)return;
  const fallback=ohFallbackTeamColor(teamId);
  shell.style.setProperty(`--${sideKey}-shirt`,fallback);
  shell.style.setProperty(`--${sideKey}-ink`,"#fff");
  const image=new Image();
  image.crossOrigin="anonymous";
  image.onload=()=>{
    try{
      const canvas=document.createElement("canvas"),size=48;
      canvas.width=size;canvas.height=size;
      const context=canvas.getContext("2d",{willReadFrequently:true});
      context.drawImage(image,0,0,size,size);
      const pixels=context.getImageData(0,0,size,size).data,buckets=new Map();
      for(let index=0;index<pixels.length;index+=4){
        const red=pixels[index],green=pixels[index+1],blue=pixels[index+2],alpha=pixels[index+3];
        if(alpha<150||red>238&&green>238&&blue>238)continue;
        const max=Math.max(red,green,blue),min=Math.min(red,green,blue),sat=max-min;
        if(max<28||sat<26)continue;
        const rgb=[Math.round(red/24)*24,Math.round(green/24)*24,Math.round(blue/24)*24].map(value=>Math.min(255,value));
        const key=rgb.join(","),score=(buckets.get(key)?.score||0)+1+sat/90;
        buckets.set(key,{rgb,score});
      }
      const winner=[...buckets.values()].sort((left,right)=>right.score-left.score)[0];
      if(!winner)return;
      const [red,green,blue]=winner.rgb,color=`rgb(${red} ${green} ${blue})`;
      shell.style.setProperty(`--${sideKey}-shirt`,color);
      shell.style.setProperty(`--${sideKey}-ink`,ohInkForColor(winner.rgb));
    }catch(_error){}
  };
  image.src=`/api/crest/${encodeURIComponent(teamId)}?palette=1`;
}

function ohWireLineupTabs(){
  qsa("[data-lineup-tab]").forEach(button=>button.onclick=()=>{
    ohLineupTab=button.dataset.lineupTab;
    qsa("[data-lineup-tab]").forEach(item=>item.classList.toggle("active",item===button));
    $("ohLineupPanel").innerHTML=ohLineupPanelMarkup();
  });
}

lineupStrip=function(lineups){
  const available=Boolean(lineups?.available);
  const confirmed=Boolean(lineups?.confirmed);
  return `<div class="lineup-strip ${confirmed?"confirmed":"pending"}">
    <div class="lineup-strip-state">
      <span class="lineup-strip-icon">${lineupCheckSvg()}</span>
      <strong>${confirmed?"Alineaciones confirmadas":"Alineaciones por confirmar"}</strong>
    </div>
    <button id="headerLineupsBtn" class="lineup-strip-button" type="button" ${available?"":"aria-disabled=\"true\""}>
      Ver alineaciones <span aria-hidden="true">›</span>
    </button>
  </div>`;
};

renderLineups=function(){
  const p=state.currentMatch||{},event=p.event||{},lineups=p.lineups||{},data=lineups.data||{};
  const structured=Boolean(data.home||data.away);
  ohLineupTab="starters";
  $("lineupsContent").innerHTML=`<div class="oh-lineups-page oh-lineups-shell">
    ${lineups.available&&structured?`
      <section class="oh-lineups-matchup"><div>${crest(event.home_team_id,event.home_team)}<strong>${esc(event.home_team||"Local")}</strong></div><b>VS</b><div>${crest(event.away_team_id,event.away_team)}<strong>${esc(event.away_team||"Visitante")}</strong></div></section>
      <div class="analysis-tabs oh-lineup-tabs"><button class="active" data-lineup-tab="starters">Titulares</button><button data-lineup-tab="substitutes">Suplentes</button><button data-lineup-tab="absences">Bajas</button></div>
      <div id="ohLineupPanel">${ohLineupPanelMarkup()}</div>`:
      `<div class="lineup-placeholder"><div><h3>Alineaciones todavía no guardadas</h3><p>${esc(lineups.reason||"Sin datos disponibles")}</p></div></div>`}
  </div>`;
  showView("lineups");
  ohWireLineupTabs();
  if(lineups.available&&structured){
    ohExtractCrestColor(event.home_team_id,"home");
    ohExtractCrestColor(event.away_team_id,"away");
  }
};

const ohBaseSetHeaderLineupsV14=setHeader;
setHeader=function(view){
  ohBaseSetHeaderLineupsV14(view);
  if(view!=="lineups")return;
  document.querySelector(".app-header")?.classList.add("match-mode");
  $("themeBtn")?.classList.add("hidden");
  const favorite=$("detailHeaderFav"),event=state.currentMatch?.event;
  if(favorite&&event){
    favorite.classList.remove("hidden");
    favorite.innerHTML=starSvg(isFav(event.event_id));
    favorite.classList.toggle("active",isFav(event.event_id));
    favorite.onclick=()=>{toggleFav(event.event_id);favorite.innerHTML=starSvg(isFav(event.event_id));favorite.classList.toggle("active",isFav(event.event_id))};
  }
};

/* OH_SQLITE_MATCH_DATA_BRIDGE_V12 */
/* OH_LINEUP_PITCH_REFERENCE_V14 */
