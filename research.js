/* All issuer/model text is escaped before it is rendered. */
let selectedReview = null;
let reviewOptionsKey = '';
let reviewSearchQuery = '';
let reviewCardKey = '';
let reviewHistoryKey = '';
let reviewStarting = false;
const reviewVerdicts = {
  worth_watching: 'Worth watching',
  no_clear_edge: 'No clear remaining edge',
  insufficient_evidence: 'More evidence needed'
};
const reviewStatuses = {complete:'Complete',running:'In progress',needs_review:'Needs evidence review',failed:'Could not complete',interrupted:'Interrupted'};
const reviewSourceNames = {issuer:'Issuer',quote:'Quote',reference:'Reference',price_change:'Price change',entry_context:'Entry context',limits:'Limitations'};
const reviewEventTypes = {earnings_or_guidance:'Earnings or guidance',product_or_service:'Product or service',commercial_agreement:'Commercial agreement',regulatory_or_legal:'Regulatory or legal',capital_or_management:'Capital or management',promotion_or_showcase:'Promotion or showcase',other:'Other event',unclear:'Unclear from excerpt'};
function reviewLink(url){try{const u=new URL(url);return u.protocol==='https:'?u.href:'#'}catch(e){return '#'}}
function normalizeAnnouncementSearch(value){
  return String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
}
function stockName(symbol){return snapshot?.stocks?.find(s=>s.symbol===symbol)?.company || ({RAAPLUSDT:'Apple',RNVDAUSDT:'NVIDIA'}[symbol]) || symbol || ''; }
function renderReviewOptions(events){
  const select=$('review-event');
  const terms=normalizeAnnouncementSearch(reviewSearchQuery).split(/\s+/).filter(Boolean);
  const matches=events.filter(event=>{
    const company=stockName(event.symbol);
    const text=normalizeAnnouncementSearch(`${company} ${event.symbol||''} ${event.title||''}`);
    return terms.every(term=>text.includes(term));
  });
  const optionsKey=JSON.stringify([reviewSearchQuery,events]);
  if(optionsKey!==reviewOptionsKey){
    const previous=select.value;
    select.innerHTML=matches.length?matches.map(e=>`<option value="${esc(e.id)}">${esc(stockName(e.symbol))} · ${esc(e.title)}</option>`).join(''):`<option value="">${events.length?'No matching announcements':'Refresh news to collect announcements'}</option>`;
    select.value=matches.some(e=>e.id===previous)?previous:(matches[0]?.id||'');
    select.disabled=!matches.length;
    $('review-search-status').textContent=!events.length?'No announcements collected yet. Use Refresh news.':!matches.length?'No matches. Try another keyword or clear your search.':terms.length?`Showing ${matches.length} of ${events.length} collected announcements.`:`${events.length} collected announcements available.`;
    reviewOptionsKey=optionsKey;
  }
  $('review-search-clear').hidden=!reviewSearchQuery;
}
function searchReviewAnnouncements(){
  reviewSearchQuery=$('review-search').value;
  renderReviewOptions(snapshot?.research?.events||[]);
  updateReviewChoice();
}
function reviewClaim(claim){
  if(!claim)return '';
  const refs=(claim.source_ids||[]).map(id=>`<a href="#review-evidence-${esc(id)}" data-evidence-ref="${esc(id)}">${esc(reviewSourceNames[id]||(id.startsWith('article_')?'Article '+Number(id.slice(8)):id))}</a>`).join('');
  return `<p>${claim.selection_origin==='amount_rule'?'<span class="pill neutral">Passage with a disclosed amount</span> ':claim.selection_origin==='assessment_citation'?'<span class="pill neutral">Cited in the final assessment</span> ':''}${esc(claim.text)}<span class="review-refs">${refs}</span></p>${claim.source_quote?`<blockquote class="review-excerpt">“${esc(claim.source_quote)}”<small>${claim.source_quote_origin==='saved_evidence'?'Selected passage copied from saved evidence · the AI’s interpretation is not independently verified':'Exact text from the cited passage · interpretation remains the model’s'}</small></blockquote>`:''}`;
}
function updateReviewChoice(){
  const data=snapshot?.research;
  const configured=data?.connection?.configured ?? snapshot?.model?.configured;
  const aiAvailable=data?.connection?.provider!=='source';
  $('review-start').textContent=aiAvailable?'Review with AI':'Read source';
  const cooling=(data?.connection?.cooldown_seconds||0)>0;
  const event=data?.events?.find(e=>e.id===$('review-event').value);
  const displayed=data?.records?.find(r=>r.id===selectedReview);
  const note=$('review-displayed-note');
  if(note){
    note.hidden=!displayed;
    note.textContent=displayed?(displayed.event.id!==event?.id?
      `Showing a different saved review below: ${displayed.event.title}. Selecting an announcement above does not change this saved result. Click Review with AI to review your selection.`:
      `${displayed.status==='running'?'Working on':'Showing saved review for'}: ${displayed.event.title} · Started ${date(displayed.started_at)}.`):'';
  }

  $('review-event-note').textContent=snapshot?.running?'Pause the paper run on Overview before reviewing, so model generation does not delay position monitoring.':event?`Published ${date(event.published_at)} · ${Date.now()/1000-event.published_at>3600?'Outside the paper-entry window; research is still available.':'Review available; paper entries have separate checks.'}`:data?.events?.length?'Choose a matching announcement to review.':'Refresh news to collect an announcement.';
  $('review-start').disabled=isPreview||reviewStarting||!event||!configured||cooling||snapshot?.busy||snapshot?.running;
  document.querySelectorAll('[data-review-again], [data-review-assess]').forEach(button=>{button.disabled=isPreview||reviewStarting||!configured||(!aiAvailable&&button.hasAttribute('data-review-assess'))||cooling||snapshot?.busy||snapshot?.running});
}
async function reviewSavedInputs(id){
  if(isPreview)return;
  reviewStarting=true;updateReviewChoice();
  try{
    const result=await api('/api/review-again',{review_id:id});
    selectedReview=result.review_id;reviewCardKey='';await refresh();
  }catch(e){toast(e.message)}finally{reviewStarting=false;updateReviewChoice()}
}
async function startReview(){
  if(isPreview)return toast('Open the local app to review an announcement.');
  reviewStarting=true;updateReviewChoice();
  try{
    const result=await api('/api/review',{event_id:$('review-event').value});
    selectedReview=result.review_id;reviewCardKey='';
    go('research');await refresh();
  }catch(e){toast(e.message)}finally{reviewStarting=false;updateReviewChoice()}
}
function chooseReview(id){selectedReview=id;reviewCardKey='';if(snapshot)renderResearch(snapshot)}
function renderResearch(data){
  const research=data.research||{events:[],records:[],active:null};
  renderResearchConnection(data);
  renderReviewOptions(research.events||[]);
  updateReviewChoice();
  $('research-observe').disabled=data.busy||isPreview;
  const active=research.active;
  $('review-progress').hidden=!active;
  if(active){
    const elapsed=Math.max(0,Math.floor(Date.now()/1000-active.started_at));
    $('review-progress').innerHTML=`<div class="review-progress-content"><span class="spinner" aria-hidden="true"></span><div><strong>${esc(active.stage)}</strong><p class="small">${elapsed}s elapsed · ${research.connection?.provider==='groq'?'Groq request · keep THESIS open. Each request allows up to 90 seconds.':'Keep the app open. Keep Ollama open; a request can take up to three minutes.'}</p></div></div>`;
  }
  const records=research.records||[];
  if(!selectedReview||!records.some(r=>r.id===selectedReview))selectedReview=records[0]?.id||null;
  const historyKey=JSON.stringify([selectedReview,records.map(r=>[r.id,r.status,r.completed_at])]);
  if(historyKey!==reviewHistoryKey){
    $('review-history').innerHTML=records.length?records.map(r=>`<button data-review-id="${esc(r.id)}" class="${r.id===selectedReview?'selected':''}"><small>${esc(r.event.symbol)} · ${date(r.started_at)}</small><strong>${esc(r.event.title)}</strong><small>${esc(r.interpretation?.presentation_status==='ai_draft'?'AI draft':reviewStatuses[r.status]||r.status)}${r.workflow==='assessment'?' · Research assessment':r.brief?' · Source brief':r.assessment?' · '+esc(reviewVerdicts[r.assessment.verdict]):''}</small></button>`).join(''):'<p class="empty">No reviews yet.</p>';
    reviewHistoryKey=historyKey;
  }
  const record=records.find(r=>r.id===selectedReview);
  updateReviewChoice();
  const key=JSON.stringify(record);
  if(!record||key===reviewCardKey)return;
  reviewCardKey=key;
  if(record.brief){renderSourceBrief(record);updateReviewChoice();return;}
  const c=record.context,a=record.assessment,e=record.event;
  const quote=c?.quote;
  const midpoint=quote?(quote.bid+quote.ask)/2:null;
  const change=c?.price_change_bps;
  const move=change==null?'Unavailable':`${change>=0?'+':''}${(change/100).toFixed(2)}%`;
  const title=a?reviewVerdicts[a.verdict]:reviewStatuses[record.status];
  const classification=a?.event_classification;
  const staged=Array.isArray(record.review_steps);
  const eventAnalysis=classification?`<div class="review-block"><h3>What actually happened <span class="pill neutral">${esc(reviewEventTypes[classification.category]||'Unclear')}</span></h3>${reviewClaim({text:classification.summary||'',source_ids:classification.source_id?[classification.source_id]:[]})}<blockquote class="review-excerpt">“${esc(classification.source_quote)}”<small>${classification.source_quote_origin==='saved_evidence'?'Selected passage copied from saved evidence · classification is the model’s interpretation':'Exact source quotation · classification is the model\'s interpretation'}</small></blockquote></div><div class="review-block"><h3>Possible business impact <span class="pill neutral">AI interpretation</span></h3>${reviewClaim(a.business_impact)}</div>`:'';
  const trigger=a?(typeof a.invalidation==='string'?`<p>${esc(a.invalidation)}</p>`:`<p>${esc(a.invalidation.evidence_needed)}</p><p class="small"><strong>Future source to check:</strong> ${esc(a.invalidation.source_to_check)}. Suggested future check; no follow-up retrieval was performed.</p>`):'';
  const article=c?.article;
  const articlePanel=article?`<div class="notice ${article.status==='retrieved'?'plain':'warning'}"><strong>${article.status==='retrieved'?'Official article retrieved':'Feed excerpt only'}</strong>${article.status==='retrieved'?`<p class="small">Retrieved ${date(article.retrieved_at)} · ${article.supplied_passages} of ${article.paragraphs.length} extracted passages supplied to Qwen (${article.supplied_characters.toLocaleString()} characters). ${article.coverage==='partial'?'Some article text was omitted to fit the local model.':'All extracted article prose was supplied.'}</p><p class="small">The page may include later updates. Issuer statements are not independently verified. Inspect the source evidence below to see exactly what the model received.</p>`:`<p class="small">${esc(article.reason)} This review uses the feed excerpt only.</p>`}</div>`:'';
  const baseline=record.comparison_baseline;
  const coverage=record.evidence_coverage;
  const coveragePanel=coverage?`<div class="notice plain"><strong>Evidence available to the final assessment</strong><p class="small">${coverage.article_source_ids.length?`${coverage.article_source_ids.length} article passages were available beyond the initial highlights. ${(coverage.quarantined_passages||[]).length} passages were excluded as possible instructions. Screening is limited; original evidence remains saved. Collection may be partial. Cut-off passages cannot be cited.`:'The issuer feed excerpt was available. No usable article passages were collected.'}</p></div>`:'';
  const audit=record.evidence_audit;
  const auditPanel=audit?`<div class="notice ${audit.status==='passed'?'plain':'warning'}"><strong>${audit.status==='passed'?'Model evidence check completed':'Draft needs evidence review'}</strong><p class="small">${esc(audit.scope)}</p>${audit.issues.length?`<ul class="audit-issues">${audit.issues.map(x=>`<li><strong>${esc(x.field.replaceAll('_',' '))} · ${esc(x.status)}</strong>${esc(x.reason)} ${reviewClaim({text:'',source_ids:x.source_ids})}</li>`).join('')}</ul>`:''}</div>`:record.status==='complete'?'<div class="notice plain">This saved review predates the separate evidence check.</div>':'';
  const draftPanel=!a&&record.draft_assessment?`<details class="draft-assessment"><summary>Inspect the unaccepted draft</summary><p class="small">This draft is retained for diagnosis. It is not an accepted assessment.</p><pre>${esc(JSON.stringify(record.draft_assessment,null,2))}</pre></details>`:'';
  const comparison=baseline?`<div class="notice plain"><strong>Review of the same saved inputs</strong><p class="small">The news, prices and capture times were reused. This is a comparison of assessments, not a new market observation or proof of improved accuracy.</p><details><summary>Previous assessment</summary><p><strong>${esc(reviewVerdicts[baseline.assessment.verdict]||baseline.assessment.verdict)}</strong></p><p>${esc(baseline.assessment.thesis.text)}</p><a href="/api/review?id=${encodeURIComponent(baseline.id)}" target="_blank" rel="noopener">Open original record ↗</a></details></div>`:'';
  const assessments=a?`
    ${comparison}${coveragePanel}${eventAnalysis}
    <div class="review-block"><h3>${staged?'Selected source evidence':'Supporting evidence'} <span class="pill neutral">${staged?'Original text':'AI assessment'}</span></h3>${a.supporting_evidence.length?a.supporting_evidence.map(reviewClaim).join(''):'<p class="small">The model did not identify sufficient supporting evidence.</p>'}</div>
    <div class="review-block"><h3>What may already be in the price <span class="pill neutral">AI assessment</span></h3>${reviewClaim(a.priced_in_assessment)}</div>
    <div class="review-challenge"><h3>The strongest counterargument</h3>${reviewClaim(a.counterargument)}</div>
    <div class="review-block"><h3>What is still unknown</h3><ul>${a.missing_information.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>
    <div class="review-block"><h3>What would change this assessment</h3>${trigger}</div>`:'';
  const checks=c?`<div class="review-block"><h3>Entry context at capture</h3><p class="small">These input checks are context, not an execution approval. No position was proposed or filled.</p>${c.checks.map(x=>`<div class="review-check"><span class="${x.passed?'check-pass':'check-wait'}" aria-label="${x.passed?'Pass':'Attention'}">${x.passed?'✓':'—'}</span><div>${esc(x.label)}<small>${esc(x.detail)}</small></div></div>`).join('')}</div>`:'';
  const evidence=c?`<details class="review-details" id="review-evidence"><summary>Inspect the source evidence and limitations</summary>${(record.model_input?.evidence||c.evidence).map(x=>`<div class="review-evidence-row" id="review-evidence-${esc(x.id)}"><h3>${esc(x.title)} <span class="pill neutral">${esc(x.kind)}</span>${x.url?` · <a href="${esc(reviewLink(x.url))}" target="_blank" rel="noopener noreferrer">Source ↗</a>`:''}</h3><p>${esc(x.text)}</p></div>`).join('')}</details>`:'';
  $('review-card').innerHTML=`<article class="card review-result"><div class="review-result-top"><div class="eyebrow">Announcement review · ${esc(e.symbol)}</div><span class="pill ${!a?'warning':'neutral'}">${record.status==='complete'?'Model response received':esc(reviewStatuses[record.status])}</span><h2>${esc(title)}</h2>${a?reviewClaim(a.thesis):`<p class="sub">${record.status==='running'?'Collecting evidence and selecting source passages.':'No valid AI assessment was recorded.'}</p>`}<div class="review-meta"><span>Model: ${esc(record.model)}</span><span>Reviewed ${date(record.started_at)}</span>${record.model_seconds!=null?`<span>Model ${staged?'calls':'call'} ${record.model_seconds.toFixed(1)}s</span>`:''}</div></div><div class="review-result-body"><a class="review-source-title" href="${esc(reviewLink(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><p class="small">Published ${date(e.published_at)} · First collected ${date(e.observed_at)} · Issuer feed excerpt</p>${record.error?`<div class="notice warning">${esc(record.error)}</div>`:''}${c?`<div class="review-facts"><div class="review-fact"><span>Bitget midpoint · observed</span><strong>${midpoint==null?'Unavailable':money(midpoint)}</strong><small>${quote?date(quote.timestamp):'No quote collected'}</small></div><div class="review-fact"><span>Change since pre-event candle</span><strong>${move}</strong><small>${esc(date(e.published_at))} → ${esc(date(c.captured_at))} · Does not establish cause</small></div><div class="review-fact"><span>Quoted spread · computed</span><strong>${c.spread_bps==null?'Unavailable':c.spread_bps.toFixed(1)+' bps'}</strong><small>Top of book at capture</small></div></div><p class="small">Market snapshot captured ${date(c.captured_at)}. These saved prices are not a current trading quote.</p>`:''}${articlePanel}${record.status!=='running'&&record.reviewer_version!=='source-brief-061'?'<div class="notice warning"><strong>Earlier AI review</strong><p class="small">This review used generated explanations. Testing found unsupported claims and missed errors in the same-model evidence check. Its original record is preserved; a completed status or earlier audit pass does not verify these claims.</p></div>':''}${auditPanel}${draftPanel}${assessments}${checks}<div class="notice plain">Research only · No trade was placed. This review is excluded from the paper-performance comparison.</div>${evidence}${record.status==='running'?'<p class="small">The full saved record will be available when this review finishes.</p>':`<a class="review-record-link" href="/api/review?id=${encodeURIComponent(record.id)}" target="_blank" rel="noopener">Open full saved record ↗</a>`}</div></article>`;
  if(record.status==='complete'&&c){
    const body=$('review-card').querySelector('.review-result-body');
    body.insertAdjacentHTML('beforeend',`<div class="review-repeat"><button data-review-again="${esc(record.id)}">Review saved inputs again</button><p class="small">Reuse this exact evidence and price snapshot; this button does not fetch article text. For a new article retrieval, select the announcement above and click Review with AI. Leave paper monitoring paused.</p></div>`);
    updateReviewChoice();
  }
}
function renderSourceBrief(record){
  const b=record.brief,c=record.context,e=record.event;
  const lookup=new Map(b.passages.map(x=>[x.id,x]));
  const chosen=b.category_origin==='not_classified'?b.passages:[...new Set([...b.highlight_ids,...b.amount_source_ids])].map(id=>lookup.get(id)).filter(Boolean);
  const others=b.passages.filter(x=>!chosen.some(y=>x.id===y.id));
  const passage=row=>`<div class="review-block"><p class="small">${esc(row.title)} · ${row.highlighted_by_model?'AI highlight':row.contains_amount?'Amount retained by the app':'Collected passage'}${row.contains_amount&&row.highlighted_by_model?' · Contains an amount':''}</p>${reviewClaim({text:'',source_ids:[row.id]})}<blockquote class="review-excerpt">${esc(row.text)}<small>Copied exactly from saved source text.</small></blockquote></div>`;
  const q=c?.quote, midpoint=q?(q.bid+q.ask)/2:null,change=c?.price_change_bps;
  const move=change==null?'Unavailable':`${change>=0?'+':''}${(change/100).toFixed(2)}%`;
  const article=c?.article;
  const coverage=article?article.status==='retrieved'?`${article.supplied_passages} of ${article.paragraphs.length} extracted article passages collected. ${article.coverage==='partial'?'Collection was partial.':'All extracted prose was collected.'}`:`Feed excerpt only. ${article.reason||'Article unavailable.'}`:'Feed excerpt only.';
  const baseline=record.comparison_baseline;
  const isAssessment=record.workflow==='assessment';
  const all=record.model_input?.evidence||c?.evidence||[];
  $('review-card').innerHTML=`<article class="card review-result"><div class="review-result-top"><div class="eyebrow">${isAssessment?'Research assessment':'Evidence brief'} · ${esc(e.symbol)}</div><span class="pill neutral">${isAssessment?esc(record.interpretation?.presentation_status==='ai_draft'?'AI draft ready':reviewStatuses[record.status]||record.status):'Source passages ready'}</span><h2>${esc(b.category_origin==='not_classified'?'Source evidence':reviewEventTypes[b.category]||'Unclear event')}</h2><p class="sub">${isAssessment?'AI interpretation of a saved source brief. Inspect the cited evidence below.':b.category_origin==='not_classified'?'Original source passages. No AI classification or assessment was made.':'AI chose the category and highlights. Read the issuer’s exact statements and conditions below.'}</p><div class="review-meta"><span>Model: ${esc(record.model)}</span><span>Reviewed ${date(record.started_at)}</span><span>${isAssessment?'Assessment call':'Model call'} ${(record.model_seconds||0).toFixed(1)}s</span></div></div><div class="review-result-body">${renderInterpretation(record)}<a class="review-source-title" href="${esc(reviewLink(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><p class="small">Published ${date(e.published_at)} · First collected ${date(e.observed_at)}</p>${baseline?`<div class="notice plain">Uses the same saved source and price snapshot as an earlier review. <a href="/api/review?id=${encodeURIComponent(baseline.id)}" target="_blank" rel="noopener">Original record ↗</a></div>`:''}<div class="review-facts"><div class="review-fact"><span>Bitget midpoint · saved</span><strong>${midpoint==null?'Unavailable':money(midpoint)}</strong><small>${q?date(q.timestamp):'No quote'}</small></div><div class="review-fact"><span>Change since pre-event candle</span><strong>${move}</strong><small>${date(e.published_at)} → ${date(c?.captured_at)}</small></div><div class="review-fact"><span>Quoted spread</span><strong>${c?.spread_bps==null?'Unavailable':c.spread_bps.toFixed(1)+' bps'}</strong><small>At capture</small></div></div><p class="small">Saved observations, not current trading quotes. Price movement does not establish cause.</p><div class="notice plain"><strong>What the source says</strong><p class="small">${esc(coverage)} ${b.passages.length} eligible passages retained. Statements below are issuer claims, not independently verified outcomes.</p></div>${chosen.map(passage).join('')}${others.length?`<details class="review-details"><summary>Read ${others.length} other collected passage${others.length===1?'':'s'}</summary>${others.map(passage).join('')}</details>`:''}<div class="review-block"><h3>How much is already in the price?</h3><p><strong>Not determined from these inputs.</strong> ${esc(b.pricing_explanation)}</p></div><div class="review-block"><h3>Follow the evidence</h3><p>${esc(b.follow_up)}</p><a href="${esc(reviewLink(e.url))}" target="_blank" rel="noopener noreferrer">Open issuer announcement ↗</a><p class="small">${isAssessment?"No follow-up source has been retrieved by this assessment.":"No follow-up retrieval or commercial-effect forecast was performed."}</p></div>${c?`<details class="review-details"><summary>Entry context at capture</summary><p class="small">These checks do not approve an order. No position was proposed.</p>${c.checks.map(x=>`<div class="review-check"><span class="${x.passed?'check-pass':'check-wait'}">${x.passed?'✓':'—'}</span><div>${esc(x.label)}<small>${esc(x.detail)}</small></div></div>`).join('')}</details>`:''}<div class="notice plain">${b.category_origin==='not_classified'?'Source reader · No AI call or trade. Read the original issuer statements.':'Research only · No trade or trading verdict. AI category and highlight quality still require judgment.'}</div><details class="review-details" id="review-evidence"><summary>Inspect collected inputs and exclusions</summary>${all.map(row=>`<div class="review-evidence-row" id="review-evidence-${esc(row.id)}"><h3>${esc(row.title||row.id)}</h3>${b.excluded_passages.some(x=>x.id===row.id)?`<p class="small">Excluded from brief: ${esc(b.excluded_passages.find(x=>x.id===row.id).reason)}</p>`:''}<p>${esc(row.text)}</p></div>`).join('')}</details><a class="review-record-link" href="/api/review?id=${encodeURIComponent(record.id)}" target="_blank" rel="noopener">Open full saved record ↗</a>${record.status==='complete'?`<div class="review-repeat"><button data-review-again="${esc(record.id)}">Review saved inputs again</button><p class="small">Reuses this exact saved evidence. For fresh inputs, select the announcement above and click Review with AI.</p></div>`:''}</div></article>`;
}

const researchActionLabels={investigate_further:'Investigate further',wait_for_details:'Wait for more evidence'};
const researchChannelLabels={revenue_or_demand:'Revenue or demand',cost_or_margin:'Cost or margin',financing_or_capital:'Financing or capital',operations_or_product:'Operations or product',regulatory_or_legal:'Regulatory or legal',unclear:'Unclear'};
const researchStatusLabels={reported:'Issuer-reported',conditional:'Conditional effect',not_established:'Effect not established'};
async function assessReview(id){
  if(isPreview)return toast('Open the local app to assess this evidence.');
  reviewStarting=true;updateReviewChoice();
  try{
    const result=await api('/api/review-assess',{review_id:id});
    selectedReview=result.review_id;reviewCardKey='';await refresh();
  }catch(e){toast(e.message)}finally{reviewStarting=false;updateReviewChoice()}
}
function renderInterpretation(record){
  const draft=record.interpretation;
  const target=record.status==='complete'?record.id:record.comparison_baseline?.id;
  if(record.workflow==='assessment'&&!draft){
    return `<section class="assessment-panel"><h3>${record.status==='running'?'Assessing this evidence…':'Assessment could not complete'}</h3><p>${record.status==='running'?'Reading the saved source passages. The original brief remains below.':esc(record.error||'No completed assessment was returned.')}</p>${renderValidationIssues(record)}${record.status!=='running'&&target?`<button data-review-assess="${esc(target)}">Try assessment again</button>`:''}<p class="small">The original source brief is preserved. No trade was placed.</p></section>`;
  }
  if(!draft){
    return `<section class="assessment-panel"><div class="eyebrow">Next · Understand the implications</div><h3>What does this evidence change?</h3><p>Ask the research model for business meaning, limitations and the next evidence to check.</p><button class="primary" data-review-assess="${esc(record.id)}">Assess evidence</button><p class="small">One additional model call using this saved brief. No new prices are fetched; no trade is placed.</p></section>`;
  }
  const byId=new Map(record.brief.passages.map(p=>[p.id,p]));
  const claim=(heading,item)=>`<div class="assessment-claim"><h3>${heading}</h3>${reviewClaim(item)}<details class="assessment-citations"><summary>Read cited source passage${item.source_ids.length===1?'':'s'}</summary>${item.source_ids.map(id=>`<blockquote class="review-excerpt">${esc(byId.get(id)?.text||'Source unavailable')}<small>${esc(byId.get(id)?.title||id)} · Saved issuer text</small></blockquote>`).join('')}</details></div>`;
  const next=draft.next_check;
  const entry=record.entry_readiness;
  return `<section class="assessment-panel"><div class="eyebrow">AI draft · Research priority</div><h2>${esc(researchActionLabels[draft.research_action]||draft.research_action)}</h2>${reviewClaim(draft.action_reason)}<p class="small">Interpretation is not independently verified. Inspect the citations and challenge the conclusion.</p>${renderConditionMappings(draft)}${claim('What changed',draft.change)}<div class="pills assessment-tags"><span class="pill neutral">${esc(researchChannelLabels[draft.business_effect.channel]||draft.business_effect.channel)}</span><span class="pill neutral">${esc(researchStatusLabels[draft.business_effect.status]||draft.business_effect.status)}</span></div>${claim('Possible business meaning',draft.business_effect)}${claim('Strongest limitation',draft.limitation)}${claim('What to check next',{text:next.observation,source_ids:next.source_ids})}<p><strong>Future source to check:</strong> ${esc(next.source_to_check)}</p><p class="small">Proposed follow-up; this source has not been retrieved by the assessment.</p>${entry?`<details class="assessment-citations"><summary>Paper-entry checks in the saved snapshot</summary><p>${esc(entry.message)}</p>${entry.failed_checks.map(c=>`<p class="small"><strong>${esc(c.label)}:</strong> ${esc(c.detail)}</p>`).join('')}<p class="small">This is historical input context, not a current execution approval.</p></details>`:''}<p class="small">Assessment saved separately from its source brief. No order was proposed or placed.</p></section>`;
}

$('review-event').addEventListener('change',updateReviewChoice);
$('review-search-form').addEventListener('submit',event=>{event.preventDefault();searchReviewAnnouncements()});
$('review-search').addEventListener('input',searchReviewAnnouncements);
$('review-search-clear').addEventListener('click',()=>{$('review-search').value='';searchReviewAnnouncements();$('review-search').focus()});
$('review-history').addEventListener('click',e=>{const b=e.target.closest('button[data-review-id]');if(b)chooseReview(b.dataset.reviewId)});
$('review-card').addEventListener('click',e=>{const assessment=e.target.closest('[data-review-assess]');if(assessment&&!assessment.disabled){assessReview(assessment.dataset.reviewAssess);return}const b=e.target.closest('[data-review-again]');if(b&&!b.disabled){reviewSavedInputs(b.dataset.reviewAgain);return}const a=e.target.closest('[data-evidence-ref]');if(a){const details=$('review-evidence');if(details)details.open=true}});

function renderValidationIssues(record){
  const issues=(record.review_steps||[]).flatMap(s=>s.validation_issues||[]);
  return issues.length?`<details class="assessment-citations"><summary>Why this draft was rejected</summary><ul>${issues.map(t=>`<li>${esc(t)}</li>`).join('')}</ul><p class="small">The original source brief remains available. No answer was silently repaired.</p></details>`:'';
}
function renderConditionMappings(draft){
  if(!draft.source_excerpt||!Array.isArray(draft.conditions))return '';
  const status={pending:'Pending',satisfied:'Satisfied',not_stated:'Status not stated'};
  const excerpt=draft.source_excerpt;
  return `<div class="assessment-source"><h3>The announcement in the source’s words</h3><blockquote class="review-excerpt">${esc(excerpt.quote)}<small>${esc(excerpt.source_id)} · Exact source text</small></blockquote></div><section class="condition-mappings"><h3>What depends on what?</h3><p class="small">AI-mapped relationships. Quoted words were checked against the source; the relationship and status still need your judgment.</p>${draft.conditions.length?draft.conditions.map(row=>`<article class="condition-row"><div class="condition-pair"><div><span class="small">Outcome</span><strong>${esc(row.outcome_span)}</strong></div><div><span class="small">Condition</span><strong>${esc(row.condition_span)}</strong></div><span class="pill neutral">${esc(status[row.condition_status]||row.condition_status)}</span></div><blockquote class="review-excerpt">${esc(row.quote)}<small>${esc(row.source_id)} · Exact source text</small></blockquote></article>`).join(''):'<p>No explicit condition link was selected. This does not establish that the announcement has no conditions.</p>'}</section>`;
}
function renderResearchConnection(data){
  const c=data.research?.connection;
  const state=$('groq-connection-state');if(!state)return;
  const groq=c?.provider==='groq';
  state.textContent=groq?`Groq · GPT-OSS 120B · ${c.connection_tested?'API response received this session':'Key loaded; connection not tested yet'}`:c?.provider==='source'?'Source reader ready · no API key needed':`Local research model: ${data.model?.name||'not configured'}`;
  const pacing=$('groq-pacing');if(pacing)pacing.textContent=groq?(c.cooldown_seconds?`Next research request available in ${c.cooldown_seconds}s. Requests are paced for the free plan.`:'Ready for a research request. One request per minute; no automatic retries.'):'Read source passages without a key. A local Ollama model enables optional AI explanations.';
  const disconnect=$('groq-disconnect');if(disconnect){disconnect.hidden=!groq;disconnect.disabled=Boolean(data.busy)||isPreview;}
  const connect=$('groq-connect');if(connect)connect.disabled=Boolean(data.busy)||isPreview;
}
$('groq-form')?.addEventListener('submit',async e=>{
  e.preventDefault();if(isPreview)return;
  const button=$('groq-connect');button.disabled=true;
  const key=$('groq-key').value;$('groq-key').value='';
  try{await api('/api/research-groq',{key});$('groq-connection-details').open=false;reviewCardKey='';await refresh();toast('Groq key loaded for research. Choose a source brief, then Assess evidence.');}
  catch(error){toast(error.message)}finally{button.disabled=Boolean(snapshot?.busy);}
});
$('groq-disconnect')?.addEventListener('click',async()=>{
  if(isPreview)return;
  try{await api('/api/research-groq',{key:''});await refresh();toast('Research uses the existing model again.');}catch(error){toast(error.message)}
});
if(typeof snapshot!=='undefined'&&snapshot)renderResearch(snapshot);
