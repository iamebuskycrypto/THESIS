/* DOM-independent rendering checks. These do not claim visual browser coverage. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const baseline = JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/apple-review-04.json'),'utf8'));
const elements = new Map();
function element(id) {
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,
    addEventListener(){},querySelector(){return {insertAdjacentHTML:(_,html)=>{element(id).innerHTML+=html}}}});
  return elements.get(id);
}
const escape = text => String(text??'').replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const context = vm.createContext({$:element,esc:escape,date:n=>String(n),money:n=>n.toFixed(2),
  URL,Date,encodeURIComponent,snapshot:null,isPreview:false,
  document:{querySelectorAll:()=>[]},toast(){},go(){},api(){},refresh(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../research.js'),'utf8'),context);
function render(record) {
  context.snapshot = {busy:false,running:false,model:{configured:true},research:{events:[],records:[record],active:null}};
  vm.runInContext('renderResearch(snapshot)',context);
  return element('review-card').innerHTML;
}
let output = render(baseline);
assert.ok(output.includes('A clear correlation between the announcement'));
assert.ok(output.includes('Review saved inputs again'));
assert.ok(!output.includes('[object Object]'));
console.log('PASS legacy saved review remains readable and offers comparison');
const newer = structuredClone(baseline);
newer.id='b'.repeat(32);
newer.comparison_baseline={id:baseline.id,assessment:baseline.assessment};
newer.assessment.event_classification={category:'promotion_or_showcase',summary:'A photography exhibition',source_quote:'<img src=x onerror=alert(1)>'};
newer.assessment.business_impact={text:'Possible <b>impact</b>',source_ids:['issuer']};
newer.assessment.invalidation={evidence_needed:'Quantified sales evidence',source_to_check:'Issuer financial releases'};
newer.model_input={evidence:baseline.context.evidence.filter(row=>row.id!=='entry_context')};
output=render(newer);
for(const text of ['What actually happened','Promotion or showcase','Possible business impact','Quantified sales evidence','Future source to check','Previous assessment','same saved inputs'])assert.ok(output.includes(text),text);
assert.ok(output.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert.ok(!output.includes('<img src=x'));
assert.ok(!output.includes('id="review-evidence-entry_context"'));
assert.ok(output.includes('Calendar closure; token weekend precedence'));
console.log('PASS new review sections escape model text and distinguish model inputs from execution checks');
const failed=structuredClone(newer);failed.id='c'.repeat(32);failed.status='failed';failed.assessment=null;failed.error='A quote could not be verified';
output=render(failed);
assert.ok(output.includes('No valid AI assessment was recorded'));
assert.ok(output.includes('A quote could not be verified'));
assert.ok(!output.includes('data-review-again'));
console.log('PASS failed comparison has an explicit error and no substitute assessment');
const articleReview=structuredClone(newer);articleReview.id='d'.repeat(32);
articleReview.context.article={status:'retrieved',retrieved_at:1789830000,supplied_passages:2,supplied_characters:333,paragraphs:['one','two','three'],coverage:'partial'};
articleReview.assessment.supporting_evidence=[{text:'A financing disclosure',source_ids:['article_001'],source_quote:'<script>untrusted</script>'}];
articleReview.model_input.evidence.push({id:'article_001',title:'Official article · passage 1',kind:'observed',text:'<script>untrusted</script>',url:'https://nvidianews.nvidia.com/news/fixture'});
output=render(articleReview);
for(const text of ['Official article retrieved','2 of 3','Some article text was omitted','Article 1','&lt;script&gt;untrusted&lt;/script&gt;','This button does not fetch article text'.toLowerCase()])assert.ok(output.includes(text),text);
assert.ok(!output.includes('<script>untrusted'));
console.log('PASS article coverage, citations, exact quotations and retrieval scope are visible');
const excerptReview=structuredClone(articleReview);excerptReview.id='e'.repeat(32);excerptReview.context.article={status:'unavailable',reason:'Test timeout'};
output=render(excerptReview);assert.ok(output.includes('Feed excerpt only'));assert.ok(output.includes('Test timeout'));
const running=structuredClone(articleReview);running.id='f'.repeat(32);running.status='running';running.assessment=null;
output=render(running);assert.ok(!output.includes('Open full saved record'));assert.ok(output.includes('available when this review finishes'));
console.log('PASS retrieval failure is explicit and pending records are not offered for export');
const selectedPassages=structuredClone(articleReview);selectedPassages.id='9'.repeat(32);
selectedPassages.assessment.event_classification.source_id='article_001';
selectedPassages.assessment.event_classification.source_quote_origin='saved_evidence';
selectedPassages.assessment.supporting_evidence[0].source_quote_origin='saved_evidence';
selectedPassages.assessment.supporting_evidence[0].source_quote='<script>untrusted text</script> $3.5 billion in convertible bonds.';
output=render(selectedPassages);
assert.ok(output.includes('Selected passage copied from saved evidence'));
assert.ok(output.includes('interpretation is not independently verified'));
assert.ok(output.includes('href="#review-evidence-article_001"'));
assert.ok(output.includes('&lt;script&gt;untrusted text&lt;/script&gt;'));
assert.ok(!output.includes('<script>untrusted text'));
console.log('PASS app-copied passages are escaped, linked and distinguished from model interpretation');
const stagedReview=structuredClone(selectedPassages);stagedReview.id='8'.repeat(32);
stagedReview.review_steps=[{name:'selection',status:'complete'},{name:'assessment',status:'complete'}];
stagedReview.assessment.event_classification.summary='';
stagedReview.assessment.supporting_evidence[0].selection_origin='amount_rule';
stagedReview.assessment.supporting_evidence[0].text='';
output=render(stagedReview);
assert.ok(output.includes('Selected source evidence'));
assert.ok(output.includes('Original text'));
assert.ok(output.includes('Passage with a disclosed amount'));
assert.ok(!output.includes('undefined'));
console.log('PASS two-step reviews distinguish copied source passages and rule-retained amounts');
const coverageReview=structuredClone(stagedReview);coverageReview.id='7'.repeat(32);
coverageReview.evidence_coverage={article_source_ids:['article_001','article_002'],excluded_citation_source_ids:[]};
coverageReview.assessment.supporting_evidence[0].selection_origin='assessment_citation';
output=render(coverageReview);
assert.ok(output.includes('2 article passages were available'));
assert.ok(output.includes('Collection may be partial'));
assert.ok(output.includes('Cited in the final assessment'));
assert.ok(output.includes('&lt;script&gt;untrusted text&lt;/script&gt;'));
assert.ok(!output.includes('<script>untrusted text'));
console.log('PASS evidence coverage and additional final citations retain scope and escaping');

const disputed=structuredClone(newer);disputed.id='f'.repeat(32);disputed.status='needs_review';disputed.draft_assessment=disputed.assessment;disputed.assessment=null;
disputed.evidence_audit={status:'needs_review',scope:'Same-model check; not proof.',issues:[{field:'business_impact',status:'unsupported',reason:'<script>bad</script> Agreement is not receipt of funds.',source_ids:['issuer']}]};
output=render(disputed);
assert.ok(output.includes('Needs evidence review'));
assert.ok(output.includes('Inspect the unaccepted draft'));
assert.ok(output.includes('&lt;script&gt;bad&lt;/script&gt;'));
assert.ok(!output.includes('<script>bad'));
assert.ok(!output.includes('Model response received'));
console.log('PASS disputed drafts stay unaccepted and audit findings are escaped');

const brief=structuredClone(baseline);brief.id='1'.repeat(32);brief.reviewer_version='source-brief-061';brief.assessment=null;brief.schema_version=7;
brief.brief={version:'source-brief-061',category:'capital_or_management',primary_source_id:'issuer',highlight_ids:['issuer'],amount_source_ids:['issuer'],passages:[{id:'issuer',title:'Original issuer text',text:'Agreement to issue $60 million; subject to investor approval. <script>bad</script>',highlighted_by_model:true,contains_amount:true}],excluded_passages:[],pricing_explanation:'No expectations baseline.',follow_up:'Read the issuer update.'};
brief.comparison_baseline={id:baseline.id,assessment:baseline.assessment};
output=render(brief);
for(const text of ['Source passages ready','Capital or management','Agreement to issue $60 million; subject to investor approval.','&lt;script&gt;bad&lt;/script&gt;','Not determined from these inputs','No trade or trading verdict','Review saved inputs again','Original record'])assert.ok(output.includes(text),text);
for(const text of ['<script>bad','Model evidence check completed','Possible business impact','No clear remaining edge','undefined'])assert.ok(!output.includes(text),text);
console.log('PASS source brief retains conditions, escapes text and does not claim a semantic pass');
const oldAudit=structuredClone(stagedReview);oldAudit.id='2'.repeat(32);oldAudit.evidence_audit={status:'passed',scope:'Old model check',issues:[]};
output=render(oldAudit);assert.ok(output.includes('earlier audit pass does not verify these claims'));
console.log('PASS older audit passes carry the observed reliability limitation');

output=render(brief);
assert.ok(output.includes('data-review-assess="'+brief.id+'"'));
assert.ok(output.includes('One additional model call using this saved brief'));
output=render(baseline);
assert.ok(!output.includes('data-review-assess'));
console.log('PASS assessment is offered on a source brief, not an older ungrounded review');

const explained=structuredClone(brief);explained.id='3'.repeat(32);explained.workflow='assessment';
const ref=text=>({text,source_ids:['issuer']});
explained.interpretation={research_action:'investigate_further',action_reason:ref('A financing agreement has unresolved conditions.'),
  change:ref('The issuer signed a financing agreement. <img onerror=bad>'),
  business_effect:{...ref('Funding depends on investor approval.'),channel:'financing_or_capital',status:'conditional'},
  limitation:ref('Signing does not establish receipt of cash.'),
  next_check:{observation:'Look for confirmation of closing.',source_to_check:'Issuer quarterly filing.',source_ids:['issuer']}};
explained.entry_readiness={message:'Saved checks blocked entry.',failed_checks:[{label:'Stale news',detail:'Old snapshot.'}],execution_approved:false};
output=render(explained);
for(const text of ['Investigate further','Possible business meaning','Strongest limitation','What to check next','Read cited source passage','Saved checks blocked entry','Interpretation is not independently verified','&lt;img onerror=bad&gt;','&lt;script&gt;bad&lt;/script&gt;','Conditional effect'])assert.ok(output.includes(text),text);
assert.ok(!output.includes('<img onerror=bad>'));
assert.ok(!output.includes('commercial-effect forecast was performed'));
console.log('PASS assessment is cited, escaped and separate from execution approval');

const pending=structuredClone(explained);pending.id='4'.repeat(32);pending.status='running';pending.interpretation=null;
output=render(pending);
assert.ok(output.includes('Assessing this evidence…'));assert.ok(output.includes('Agreement to issue $60 million'));
assert.ok(!output.includes('data-review-assess'));
const rejected=structuredClone(pending);rejected.id='5'.repeat(32);rejected.status='failed';rejected.error='<b>Bad source reference</b>';
rejected.comparison_baseline={id:brief.id};output=render(rejected);
assert.ok(output.includes('&lt;b&gt;Bad source reference&lt;/b&gt;'));
assert.ok(output.includes('data-review-assess="'+brief.id+'"'));
assert.ok(output.includes('The original source brief is preserved'));
console.log('PASS pending and failed assessments preserve source text and expose only manual retry');

context.snapshot.research.events=[{id:'new-choice',title:'New selected event',published_at:Date.now()/1000}];
element('review-event').value='new-choice';vm.runInContext('updateReviewChoice()',context);
assert.ok(element('review-displayed-note').textContent.includes('Showing a different saved review below'));
assert.ok(element('review-displayed-note').textContent.includes(brief.event.title));
context.snapshot.research.events=[rejected.event];element('review-event').value=rejected.event.id;
vm.runInContext('updateReviewChoice()',context);
assert.ok(element('review-displayed-note').textContent.startsWith('Showing saved review for'));
console.log('PASS selected announcement and displayed saved review are distinguished');

const button={disabled:false};context.document.querySelectorAll=()=>[button];
context.snapshot.busy=true;vm.runInContext('updateReviewChoice()',context);assert.equal(button.disabled,true);
context.snapshot.busy=false;context.isPreview=true;vm.runInContext('updateReviewChoice()',context);assert.equal(button.disabled,true);
context.isPreview=false;vm.runInContext('updateReviewChoice()',context);assert.equal(button.disabled,false);
console.log('PASS assessment action is disabled while busy and in preview');

(async()=>{
 const calls=[];context.api=async(url,body)=>{calls.push([url,body.review_id]);return {review_id:'6'.repeat(32)}};
 await vm.runInContext('assessReview("'+brief.id+'")',context);
 assert.deepEqual(calls,[['/api/review-assess',brief.id]]);
 assert.equal(button.disabled,false);
 console.log('PASS assessment sends one request for the explicit saved record');
})().catch(error=>{console.error(error);process.exitCode=1});
