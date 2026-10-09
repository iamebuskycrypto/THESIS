/* Browser-independent DOM doubles: race handling, escaping and browser saves. */
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('switching stocks discards old requests and source text is escaped',async()=>{
 const elements=new Map();const element=id=>{if(!elements.has(id))elements.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,addEventListener(name,fn){this[name]=fn},scrollIntoView(){}});return elements.get(id)};
 const pending=[];const stored=new Map();const stocks=[{symbol:'RAAPLUSDT',company:'Apple',ticker:'AAPL',source_url:'https://www.apple.com/newsroom/rss-feed.rss'},{symbol:'RAMDUSDT',company:'AMD',ticker:'AMD',source_url:'https://ir.amd.com/news-events/press-releases/rss'}];
 const ctx=vm.createContext({document:{getElementById:element},URL,URLSearchParams,console,structuredClone,Date,setTimeout,clearTimeout,setInterval(){},matchMedia:()=>({matches:true}),localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},fetch:async url=>{const p=new URL(url,'http://localhost').searchParams;if(p.get('action')==='stocks')return{ok:true,json:async()=>({stocks})};return new Promise(resolve=>pending.push({action:p.get('action'),symbol:p.get('symbol'),resolve:body=>resolve({ok:true,json:async()=>body})}))}});
 vm.runInContext(fs.readFileSync('public/reader.js','utf8'),ctx);await new Promise(r=>setImmediate(r));
 vm.runInContext("chooseStock('RAMDUSDT')",ctx);assert.match(element('company-symbol').textContent,/AMD/);
 const q=s=>({symbol:s,midpoint:10.5,spread_bps:1,quote:{bid:10,ask:11,bid_size:1,ask_size:1,timestamp:Date.now()/1000,collected_at:Date.now()/1000}});
 for(const p of pending.filter(p=>p.symbol==='RAAPLUSDT'))p.resolve(p.action==='quote'?q(p.symbol):{events:[{id:'wrong',title:'Old Apple'}],collected_at:Date.now()/1000});
 for(const p of pending.filter(p=>p.symbol==='RAMDUSDT'))p.resolve(p.action==='quote'?q(p.symbol):{events:[{id:'right',title:'AMD <script>bad</script>',published_at:Date.now()/1000,url:'https://ir.amd.com/news'}],collected_at:Date.now()/1000});
 await new Promise(r=>setImmediate(r));assert.ok(!element('news').innerHTML.includes('Old Apple'));assert.ok(element('news').innerHTML.includes('&lt;script&gt;'));assert.ok(!element('news').innerHTML.includes('<script>bad'));
 vm.runInContext("openSource('right')",ctx);const p=pending.find(p=>p.action==='source');p.resolve({mode:'source_reader',event:{id:'right',symbol:'RAMDUSDT',title:'AMD source',url:'https://ir.amd.com/news',text:'<img src=x onerror=alert(1)>',published_at:1},article:{status:'unavailable'},passages:[],captured_at:2,scope:'No AI call.'});await new Promise(r=>setImmediate(r));
 assert.match(element('source').innerHTML,/Feed excerpt only/);assert.match(element('source').innerHTML,/&lt;img/);assert.ok(!element('source').innerHTML.includes('<img src=x'));
 element('save-source').click();const record=JSON.parse([...stored.values()][0])[0];assert.equal(record.quote.symbol,'RAMDUSDT');assert.equal(record.captured_at,2);assert.equal(record.event.text,'<img src=x onerror=alert(1)>');
});
