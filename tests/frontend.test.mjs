import test from 'node:test';
import assert from 'node:assert/strict';
import {fixed,percent,shiftDecimal,esc,eligibleHedges,decimalInput,selection,american,americanToDecimal,usd,compareDecimal} from '../frontend/format.mjs';
import {oddsMatrix,toolCards} from '../frontend/presentation.mjs';
import {assertEnvelope,allPages,request,ApiError} from '../frontend/client.mjs';

const meta={format:'corner.product_api/1',data_mode:'fixture',snapshot_id:'fixture:1',production_authorized:false,availability_verified:false};
test('decimal formatting stays exact beyond binary float precision',()=>{
  assert.equal(fixed('9007199254740993.555'),'9007199254740993.56');
  assert.equal(percent('0.00999999999999999999'),'1.00%');
  assert.equal(percent('0.03',true),'+3.00%');
  assert.equal(fixed('-0.001'),'0.00');
  assert.equal(fixed('-1.005'),'-1.01');
  assert.equal(fixed(null),'—');
});
test('percentage input converts to ratio without float rounding',()=>{
  assert.equal(shiftDecimal('3.25',-2),'0.0325');
  assert.equal(shiftDecimal('0.0000000001',-2),'0.000000000001');
  assert.equal(shiftDecimal('100',-2),'1');
  assert.equal(shiftDecimal('-0.125',2),'-12.5');
});
test('American odds conversion is exact before display rounding',()=>{
  for(const [decimal,line] of [['2','+100'],['3.4','+240'],['1.5','-200'],['2.12','+112'],['1.91','-110'],['1.8','-125'],['2.125','+113'],['1.000000000001','-100000000000000']])assert.equal(american(decimal),line);
  assert.equal(american(null),'—');
  for(const invalid of ['1','0','-2','NaN'])assert.throws(()=>american(invalid));
  assert.equal(americanToDecimal('+150'),'2.5');assert.equal(americanToDecimal('-200'),'1.5');
  assert.equal(americanToDecimal('-110'),'1.909090909091');
  for(const invalid of ['110','-99','+0','1e3','+100.5','NaN'])assert.throws(()=>americanToDecimal(invalid));
});
test('USD grouping and signs preserve exact large monetary values',()=>{
  assert.equal(usd('9007199254740993.555'),'$9,007,199,254,740,993.56');
  assert.equal(usd('-1234.005'),'-$1,234.01');assert.equal(usd('-0.001'),'$0.00');assert.equal(usd(null),'—');
  assert.equal(compareDecimal('1.999999999999999999','2'),-1);assert.equal(compareDecimal('-2','-1.0'),-1);
});
test('odds grid separates contracts and uses exact raw-price order',()=>{
  const q={id:'q1',contract_id:'c1',market_key:'h2h',selection_id:'home',selection_name:'Home',point:null,sportsbook_id:'a',decimal_odds:'2.000000000000000001',commission_rate:'0'};
  const html=oddsMatrix([q,{...q,id:'q2',sportsbook_id:'b',decimal_odds:'2'},{...q,id:'q3',contract_id:'c2',point:'3.5',market_key:'spreads'}],[{id:'a',name:'A'},{id:'b',name:'B'}]);
  assert.match(html,/Moneyline · c1/);assert.match(html,/Spreads · c2/);
  assert.equal((html.match(/class="best-line"/g)||[]).length,2);
  assert.match(html,/<strong>\+100<\/strong><small>A<\/small>/);
  assert.match(html,/data-id="q1"/);
});
test('bet cards retain every leg and distinguish middle payoff from EV',()=>{
  const qs=[{id:'a',market_key:'totals',selection_name:'Over',point:'210.5',decimal_odds:'1.95',sportsbook_id:'a',commission_rate:'0'},{id:'b',market_key:'totals',selection_name:'Under',point:'214.5',decimal_odds:'1.95',sportsbook_id:'b',commission_rate:'0'}];
  const row={id:'middle',kind:'middle',game_id:'g',market_key:'totals',capital_required:'200',minimum_profit:'-5',calculation:{legs:qs.map(q=>({quote_id:q.id,stake:'100'})),double_win_ranges:[[211,214]],payoff:{maximum_modeled_profit:'190'}}};
  const html=toolCards([row],{game:()=>({name:'A vs B',sport_key:'basketball_nba',starts_at:'2030-01-01T00:00:00Z'}),quote:id=>qs.find(q=>q.id===id),badge:id=>id});
  assert.match(html,/BEST MODELED PAYOFF/);assert.match(html,/\$190\.00/);assert.match(html,/-\$5\.00/);assert.match(html,/Middle EV not estimated/);
  assert.equal((html.match(/class="bet-leg"/g)||[]).length,2);assert.match(html,/-105/);
});
test('HTML is escaped at the presentation boundary',()=>assert.equal(esc('<img x="&">'), '&lt;img x=&quot;&amp;&quot;&gt;'));
test('invalid decimals never become NaN displays',()=>{
  for(const x of ['NaN','Infinity','1e3','<script>'])assert.throws(()=>fixed(x));
  assert.equal(decimalInput('1.001'),true);assert.equal(decimalInput('1e3'),false);assert.equal(decimalInput('-1'),false);
});
const back={id:'back',contract_id:'c',market_key:'h2h',selection_id:'a',sportsbook_id:'book',selection_name:'A',point:null};
const away={...back,id:'away',selection_id:'b',sportsbook_id:'b'};
const lay={...back,id:'lay',market_key:'h2h_lay',sportsbook_id:'exchange'};
test('hedges match contract, direction, selection and distinct book',()=>{
  const quotes=[back,away,lay,{...lay,id:'wrong',contract_id:'d'},{...lay,id:'same',sportsbook_id:'book'}];
  assert.deepEqual(eligibleHedges(quotes,back,'lay').map(q=>q.id),['lay']);
  assert.deepEqual(eligibleHedges(quotes,back,'opposite_back').map(q=>q.id),['away']);
});
test('single opposite back cannot cover a draw',()=>{
  assert.deepEqual(eligibleHedges([back,away,{...away,id:'draw',selection_id:'draw'}],back,'opposite_back'),[]);
});
test('selection labels preserve signed line and lay direction',()=>{
  assert.equal(selection({...back,market_key:'spreads',point:'-3.5'}),'A -3.5');
  assert.equal(selection(lay),'A · Lay');
});
test('unknown environments and changed snapshots fail closed',()=>{
  assertEnvelope({meta,data:{}},'fixture:1');
  assert.throws(()=>assertEnvelope({meta:{...meta,data_mode:'live'}},'fixture:1'),ApiError);
  assert.throws(()=>assertEnvelope({meta:{...meta,production_authorized:true}},'fixture:1'),ApiError);
  assert.throws(()=>assertEnvelope({meta,data:{}},'fixture:2'),error=>error.code==='snapshot_changed');
});
test('paging always carries the same snapshot',async()=>{
  const calls=[];
  const response=await allPages('games',{loader:async(path,options)=>{
    calls.push(options);const offset=options.params.offset;
    return {meta,data:{items:offset===0?['a']:['b'],offset,next_offset:offset===0?1:null}};
  }});
  assert.deepEqual(response.items,['a','b']);assert.equal(calls[1].params.snapshot_id,'fixture:1');
});
test('changed or nonadvancing pagination is rejected',async()=>{
  await assert.rejects(allPages('games',{snapshot:'fixture:1',loader:async()=>({meta,data:{items:[],offset:0,next_offset:0}})}),ApiError);
  await assert.rejects(allPages('games',{snapshot:'fixture:2',loader:async()=>({meta,data:{items:[],offset:0,next_offset:null}})}),error=>error.code==='snapshot_changed');
});
test('POST preserves decimal strings and binds snapshot',async()=>{
  let captured;
  await request('calculators/promo',{snapshot:'fixture:1',body:{face_value:'100.001'},fetcher:async(url,options)=>{
    captured=options;return new Response(JSON.stringify({meta,data:{}}),{status:200});
  }});
  assert.equal(JSON.parse(captured.body).face_value,'100.001');assert.equal(captured.method,'POST');
});
test('network, invalid JSON, HTTP errors and missing data are not empty successes',async()=>{
  await assert.rejects(request('games',{fetcher:async()=>{throw new Error('private');}}),error=>error.code==='offline'&&!error.message.includes('private'));
  await assert.rejects(request('games',{fetcher:async()=>new Response('not json')}),error=>error.code==='invalid_response');
  await assert.rejects(request('games',{fetcher:async()=>new Response(JSON.stringify({meta}),{status:200})}),error=>error.code==='invalid_response');
  await assert.rejects(request('games',{fetcher:async()=>new Response(JSON.stringify({meta,error:{code:'snapshot_changed',message:'Reload'}}),{status:409})}),error=>error.code==='snapshot_changed');
});
test('cancelled requests stay cancelled rather than reporting offline',async()=>{
  const controller=new AbortController();controller.abort();
  await assert.rejects(request('games',{signal:controller.signal,fetcher:async()=>{throw new Error('aborted');}}),error=>error.name==='AbortError');
});
