/* Journal reads recorded outcomes only. All source/model text is escaped. */
let journalKind = 'agent';
let journalSymbol = 'all';
function journalURL(value){try{const u=new URL(value);return u.protocol==='https:'?u.href:'#'}catch(e){return '#'}}
function journalRecord(row,symbol,kind){
  const d=row.decision,f=row.fill,p=row.packet||{},sources=p.evidence||[];
  const fixed=sources.length>0&&sources.every(x=>x.source_kind==='exchange');
  const label=fixed?'Fixed risk exit':kind==='benchmark'?'Comparison rule':d?'AI decision':'Input / model failure';
  return `<details class="journal-record"><summary><span><strong>${esc(symbol)}</strong><small>${date(row.decision_time||row.observed_at||p.observed_at)} · ${esc(label)}</small></span><span class="pill ${row.status==='blocked'?'warning':'neutral'}">${esc(stateLabel(row.status))}${d?' · '+esc(d.action.toUpperCase()):''}</span></summary><div class="journal-body"><p>${esc(row.reason||'No explanation recorded.')}</p>${d?`<div class="review-block"><h3>Decision basis</h3><p>${esc(d.thesis)}</p><h3>Price assessment</h3><p>${esc(d.priced_in_assessment)}</p><h3>What would change the thesis</h3><p>${esc(d.invalidation)}</p><p class="small">The model's estimate of a remaining move is unverified; passing execution rules does not establish an investment advantage.</p></div>`:''}${f?`<div class="journal-metrics"><div><small>Simulated ${esc(f.side)}</small><strong>${Number(f.quantity).toFixed(6)} units</strong></div><div><small>Fill price</small><strong>${money(f.price)}</strong></div><div><small>Notional / fee</small><strong>${money(f.notional)} / ${money(f.fee)}</strong></div></div>`:''}<div class="review-block"><h3>Evidence supplied at the decision</h3>${sources.map(e=>`<p><a href="${esc(journalURL(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.id)} ↗</a> · ${date(e.published_at)}</p><p class="small">${esc(e.text)}</p>`).join('')||'<p class="small">No valid evidence recorded.</p>'}</div><details><summary>Full recorded decision and execution checks</summary><pre>${esc(JSON.stringify(row,null,2))}</pre></details></div></details>`;
}
function renderJournal(data){
  if(!$('journal-portfolios'))return;
  const ledgers=data.ledgers.filter(x=>x.kind===journalKind&&(journalSymbol==='all'||x.symbol===journalSymbol));
  $('journal-portfolios').innerHTML=ledgers.map(l=>{const s=l.state,m=l.summary;return `<div class="card"><div class="panel-title"><div><h2>${esc(l.symbol)}</h2><p class="small">${l.kind==='agent'?'THESIS agent':'Comparison rule'} · Separate ${money(s.policy?.initial_cash||10000)} USDT starting balance</p></div><span class="pill neutral">Paper</span></div><div class="journal-equity">${money(m.equity)} <small>USDT</small></div><p class="small">Net change ${m.net_change>=0?'+':''}${money(m.net_change)} · includes charged fees and simulated slippage</p><div class="journal-metrics"><div><small>Available cash</small><strong>${money(s.cash)}</strong></div><div><small>Position quantity</small><strong>${Number(s.quantity).toFixed(6)}</strong></div><div><small>Marked position value</small><strong>${money(s.quantity*s.last_bid)}</strong></div><div><small>Current drawdown</small><strong>${(m.drawdown*100).toFixed(2)}%</strong></div><div><small>Charged fees</small><strong>${money(m.fees)}</strong></div><div><small>Fills / decisions</small><strong>${m.fills} / ${m.decisions}</strong></div></div><p class="small">${m.marked_at?'Last monitoring mark '+date(m.marked_at):'No market mark yet.'} · Open positions are valued at the last accepted bid; prospective exit fees are not deducted. Drawdown is from the observed equity peak.</p><a href="/api/export?symbol=${encodeURIComponent(l.symbol)}&kind=${l.kind}" target="_blank" rel="noopener">Open this complete ledger ↗</a></div>`}).join('');
  const rows=ledgers.flatMap(l=>l.records.map(r=>({row:r,symbol:l.symbol,kind:l.kind}))).sort((a,b)=>(b.row.decision_time||0)-(a.row.decision_time||0));
  const el=$('journal-records');
  const key=JSON.stringify([journalKind,journalSymbol,rows]);
  if(el.dataset.key!==key){el.innerHTML=rows.length?rows.map(x=>journalRecord(x.row,x.symbol,x.kind)).join(''):'<div class="empty"><strong>No decisions recorded for this selection.</strong>Start a paper run from Overview. Only eligible new announcements enter the strategy. Waiting is normal when evidence is old or trading availability is unresolved.</div>';el.dataset.key=key;}
  $('journal-count').textContent=rows.length+' recent records';
  $('export-run').disabled=data.busy||data.running||isPreview;
  $('export-note').textContent=data.running?'Pause monitoring to export a consistent run.':data.busy?'Wait for the active request to finish before exporting.':'Download every recorded decision, portfolio mark, review and collected source file, with file hashes.';
}
async function exportRun(){
  const button=$('export-run');button.disabled=true;
  try{const response=await fetch('/api/export-run');if(!response.ok){const error=await response.json();throw new Error(error.error||'Export failed');}const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='THESIS-run-evidence.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Run evidence downloaded.');}catch(error){toast(error.message)}finally{if(snapshot)renderJournal(snapshot);}
}
$('journal-kind').addEventListener('change',e=>{journalKind=e.target.value;if(snapshot)renderJournal(snapshot)});
$('journal-symbol').addEventListener('change',e=>{journalSymbol=e.target.value;if(snapshot)renderJournal(snapshot)});
$('export-run').addEventListener('click',exportRun);
if(typeof snapshot!=='undefined'&&snapshot)renderJournal(snapshot);
