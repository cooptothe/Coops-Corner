import {request,allPages} from './client.mjs';
import {MARKETS,TITLES,esc,american,americanToDecimal,percent,usd as units,tone,selection,date,sport,decimalInput,shiftDecimal,eligibleHedges} from './format.mjs';
import {toolCards,oddsMatrix} from './presentation.mjs';

const $=id=>document.getElementById(id);
const state={view:'positive_ev',caps:null,meta:null,games:[],quotes:new Map(),filters:{},offset:0,limit:10,rows:[],page:null,loading:false,epoch:0};
let bootController, pageController, promoController, pendingPromoQuote, pendingGame;
const descriptions={positive_ev:'Compare offered odds with a complete reference-book estimate.',arbitrage:'Explore complementary positions and their decisive-settlement payoffs.',middle:'Find cross-line windows. See the upside and the cost of missing the middle.',low_hold:'Compare rounded payoff tables with a bounded modeled loss.',games:'One event. Every featured market. The exact quotes behind each calculation.',promo:'Explore bonus and refund economics without confusing tokens with cash.'};
const book=id=>state.caps?.books.find(b=>b.id===id)?.name || id;
const game=id=>state.games.find(g=>g.id===id);
const quote=id=>state.quotes.get(id);
const spinner=text=>`<div class="loading" role="status"><span class="spinner"></span>${esc(text)}</div>`;
const options=(items,value,all)=>`${all?`<option value="">${esc(all)}</option>`:''}${items.map(([id,label])=>`<option value="${esc(id)}" ${id===value?'selected':''}>${esc(label)}</option>`).join('')}`;
const selectFilter=(name,label,items,all)=>`<label class="field"><span>${label}</span><select name="${name}">${options(items,state.filters[name]||'',all)}</select></label>`;
function message(error,retry='retry-page') {
  const changed=error.code==='snapshot_changed';
  return `<div class="error-card" role="alert"><span class="error-symbol">!</span><h3>${changed?'This snapshot has changed':'Unable to load this view'}</h3><p>${esc(error.message)}</p>${error.fields?.length?`<small>Check: ${esc(error.fields.join(', '))}</small>`:''}<button class="button" data-action="${changed?'reload':retry}">${changed?'Reload workspace':'Try again'}</button></div>`;
}
function markConnection(ok) { $('connection').textContent=ok?'Local fixture API connected':'Local API unavailable'; $('status-dot').classList.toggle('connected',ok); }

async function bootstrap() {
  bootController?.abort(); pageController?.abort(); promoController?.abort();
  bootController=new AbortController(); const signal=bootController.signal; const epoch=++state.epoch;
  $('refresh').disabled=true; $('global-error').hidden=true; $('view').innerHTML=spinner('Connecting to your local workspace…');
  state.caps=null; state.rows=[]; state.page=null; state.meta=null; state.quotes.clear();
  try {
    const caps=await request('capabilities',{signal});
    const games=await allPages('games',{snapshot:caps.meta.snapshot_id,signal});
    const boards=await Promise.all(games.items.map(g=>allPages(`games/${encodeURIComponent(g.id)}/odds`,{snapshot:caps.meta.snapshot_id,signal})));
    if(epoch!==state.epoch)return;
    state.caps=caps.data; state.meta=caps.meta; state.games=games.items;
    state.quotes=new Map(boards.flatMap(b=>b.items).map(q=>[q.id,q]));
    $('snapshot-caption').textContent=`Fixture captured ${date(state.meta.captured_at)} · Not a live refresh`;
    markConnection(true); navigate(true);
  } catch(error) {
    if(error.name==='AbortError'||epoch!==state.epoch)return;
    markConnection(false); $('view').innerHTML=message(error,'reload'); $('snapshot-caption').textContent='No snapshot loaded';
  } finally { if(epoch===state.epoch)$('refresh').disabled=false; }
}
function navigate(reset=false) {
  const next=location.hash.slice(1) || 'positive_ev';
  const view=Object.hasOwn(TITLES,next)?next:'positive_ev';
  const changed=view!==state.view;
  if(changed || reset) { state.filters={}; state.offset=0; }
  state.view=view; pageController?.abort(); promoController?.abort(); $('detail').close();
  document.querySelectorAll('[data-view]').forEach(a=>{const selected=a.dataset.view===view;a.classList.toggle('active',selected);if(selected)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('crumb').textContent=TITLES[view]; $('title').textContent=TITLES[view]; $('subtitle').textContent=descriptions[view];
  document.title=`${TITLES[view]} — The Corner`;
  if(!state.caps)return;
  if(pendingGame && view==='positive_ev'){state.filters={game_id:pendingGame};state.offset=0;pendingGame=null;}
  renderView();
  if(pendingPromoQuote && view==='promo'){syncPromo(pendingPromoQuote);pendingPromoQuote=null;}
  if(changed)window.scrollTo({top:0,left:0});
}
function sortChoices() {
  if(state.view==='games')return [['starts_at','Start time'],['name','Event name']];
  return [...(state.view==='positive_ev'?[['conditional_ev_ratio','Conditional EV · highest']]:[['minimum_profit','Minimum payoff · highest']]),['capital_required','Capital required · lowest'],['id','Stable order']];
}
function renderView() {
  if(state.view==='promo') { renderPromo(); return; }
  const isGames=state.view==='games';
  $('view').innerHTML=`<div id="stats" class="stats" aria-label="View summary"></div>
    <section class="results-panel"><details id="filter-disclosure" class="filter-disclosure" ${matchMedia('(max-width:600px)').matches?'':'open'}><summary>Filters <span>Sport · Market · Book <span aria-hidden="true">⌄</span></span></summary><form id="filters" class="filters" aria-label="Filter results">
    ${selectFilter('sport_key','SPORT',state.caps.sports.map(s=>[s,sport(s)]),'All sports')}
    ${selectFilter('market_key','MARKET',state.caps.market_keys.map(m=>[m,MARKETS[m]]),'All markets')}
    ${isGames?`<label class="field grow"><span>SEARCH EVENTS</span><input name="search" type="search" placeholder="Find a game or tournament" maxlength="100" value="${esc(state.filters.search||'')}"></label>`:
    selectFilter('sportsbook_id','SPORTSBOOK',state.caps.books.map(b=>[b.id,b.name]),'All books')+selectFilter('game_id','EVENT',state.games.map(g=>[g.id,g.name]),'All events')}
    ${state.view==='positive_ev'||state.view==='low_hold'?`<label class="field threshold"><span>${state.view==='positive_ev'?'MIN. EV (%)':'MAX. LOSS (%)'}</span><input name="threshold" inputmode="decimal" value="${esc(state.filters.threshold ?? (state.view==='positive_ev'?'0':'1'))}" required maxlength="20" aria-describedby="filter-basis"></label>`:''}
    <button class="button apply" type="submit">Apply filters</button><button class="reset-button" type="button" data-action="clear-filters">Reset</button></form></details>
    <div class="results-toolbar"><div><h2>${isGames?'Event directory':'Market results'} <span id="result-count" class="count">—</span></h2><p id="filter-basis">${isGames?'Scheduled times are fixture data, not verified phase.':state.view==='positive_ev'?'EV is conditional on decisive settlement. No unconditional return is estimated.':state.view==='middle'?'A double-win window is not a probability model. Middle EV is not estimated.':'Payoffs assume fixed accepted prices. Common refunds may return zero profit.'}</p></div>
    <label class="sort-label">Sort by <select id="sort">${options(sortChoices(),state.filters.sort||sortChoices()[0][0])}</select></label></div>
    <div id="results" aria-live="polite" aria-busy="true"></div><div id="pagination" class="pagination"></div></section>
    <p class="fineprint"><span aria-hidden="true">ⓘ</span> Synthetic prices · American odds · USD display ($1 per calculation unit). Fixed-price examples; current availability is unverified.</p>`;
  loadPage();
}
async function loadPage() {
  pageController?.abort(); pageController=new AbortController(); const signal=pageController.signal;
  state.loading=true; state.rows=[]; state.page=null; $('results').innerHTML=spinner('Loading market results…'); $('results').setAttribute('aria-busy','true'); $('pagination').innerHTML=''; $('result-count').textContent='—'; renderStats();
  const kind=state.view, snapshot=state.meta.snapshot_id;
  const params={limit:state.limit,offset:state.offset,snapshot_id:snapshot};
  for(const k of ['sport_key','market_key',...(kind==='games'?['search']:['sportsbook_id','game_id'])])if(state.filters[k])params[k]=state.filters[k];
  const sort=state.filters.sort||sortChoices()[0][0];params.sort=sort;
  params.descending=['conditional_ev_ratio','minimum_profit'].includes(sort);
  try {
    if(kind==='positive_ev')params.minimum_ev_ratio=shiftDecimal(state.filters.threshold??'0',-2);
    if(kind==='low_hold')params.maximum_loss_ratio=shiftDecimal(state.filters.threshold??'1',-2);
    const response=await request(kind==='games'?'games':`tools/${kind}`,{params,signal,snapshot});
    if(signal.aborted||state.view!==kind)return;
    state.page=response.data;state.rows=response.data.items;state.loading=false;
    $('result-count').textContent=String(state.page.total);$('results').setAttribute('aria-busy','false');renderStats();
    if(!state.rows.length) $('results').innerHTML=`<div class="empty-state"><div class="empty-icon">⌕</div><h3>No matching ${kind==='games'?'events':'results'}</h3><p>Try a different market, book or threshold. An empty view is not a claim about the live market.</p><button class="button secondary" data-action="clear-filters">Clear filters</button></div>`;
    else $('results').innerHTML=kind==='games'?renderGames(state.rows):renderTools(state.rows);
    renderPagination();
  } catch(error) {
    if(error.name==='AbortError'||signal.aborted)return;
    state.loading=false; $('results').setAttribute('aria-busy','false');$('results').innerHTML=message(error);$('result-count').textContent='—';renderStats();
  }
}
function renderStats() {
  if(!$('stats'))return;
  const loading=state.loading || !state.page;
  const sportCount=new Set(state.rows.map(r=>r.sport_key||game(r.game_id)?.sport_key)).size;
  $('stats').innerHTML=`<article class="stat"><div><p>${state.view==='games'?'MATCHING EVENTS':'MATCHING RESULTS'}</p><strong>${loading?'—':state.page.total}</strong></div><span class="stat-symbol">${state.view==='games'?'▦':'↗'}</span><small>${loading?'Waiting for API response':'Across your current filters'}</small></article>
    <article class="stat"><div><p>SPORTS ON THIS PAGE</p><strong>${loading?'—':sportCount.toString().padStart(2,'0')}</strong></div><span class="stat-symbol neutral">◎</span><small>Featured markets only</small></article>
    <article class="stat fixture-stat"><div><p>OPERATING MODE</p><strong>Fixture only<span class="tiny-dot"></span></strong></div><small>No live execution. No production authorization.</small><span class="fixture-grid" aria-hidden="true"></span></article>`;
}
function badge(id) { const color=({demo_target:'green',demo_reference_a:'blue',demo_reference_b:'purple',demo_exchange:'amber'})[id]||'blue';return `<span class="book-badge ${color}" title="${esc(book(id))}">${esc(book(id).replace('Demo ','').replace('Reference ','Ref '))}</span>`; }
function betTitle(row) {
  const c=row.calculation;
  if(c.target_quote_id)return selection(quote(c.target_quote_id));
  if(row.kind==='middle')return c.legs.map(l=>selection(quote(l.quote_id))).join(' / ');
  if(c.back_quote_id)return `${selection(quote(c.back_quote_id))} · Back / lay`;
  return `${c.legs.length}-selection cover`;
}
function renderTools(rows) {
  return toolCards(rows,{game,quote,badge});
}
function renderGames(games) {
  return `<div class="game-grid">${games.map(g=>`<article class="game-card"><div class="game-top"><span class="league-icon">${g.sport_key.includes('basketball')?'◉':g.scope==='competition'?'⚑':'◎'}</span><span>${esc(g.competition)}</span><span class="phase-tag">Phase unknown</span></div><p class="game-time">${esc(date(g.starts_at))}</p><h3>${esc(g.name)}</h3>${oddsMatrix([...state.quotes.values()].filter(q=>q.game_id===g.id&&(!state.filters.market_key||q.market_key===state.filters.market_key)),state.caps.books)}<div class="game-bottom"><span>Best raw price before commission · American odds</span><button class="button secondary small" data-action="odds" data-id="${esc(g.id)}">Explore odds →</button></div></article>`).join('')}</div>`;
}
function renderPagination() {
  const p=state.page;
  $('pagination').innerHTML=`<span>${p.total?`${p.offset+1}–${p.offset+p.items.length}`:'0'} of ${p.total} results</span><div><label>Rows <select id="page-size">${[10,25,50].map(n=>`<option value="${n}" ${state.limit===n?'selected':''}>${n}</option>`).join('')}</select></label><button class="page-button" data-action="previous" ${p.offset===0?'disabled':''} aria-label="Previous page">←</button><button class="page-button" data-action="next" ${p.next_offset===null?'disabled':''} aria-label="Next page">→</button></div>`;
}
function openDialog(title,eyebrow,html) {
  $('detail').classList.toggle('odds-dialog',eyebrow==='EVENT ODDS BOARD');
  $('detail-title').textContent=title;$('detail-eyebrow').textContent=eyebrow;$('detail-body').innerHTML=html;$('detail').showModal();
}
function metrics(entries) { return `<dl class="detail-metrics">${entries.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`; }
function payoffTable(rows,labels=['State','Net profit']) { return `<div class="outcome-strip">${rows.map(([s,v,token])=>`<div class="outcome-tile"><small>${esc(s)}</small><strong class="${tone(v)}">${units(v)}</strong>${token!==undefined?`<small>Token face ${units(token)}</small>`:''}</div>`).join('')}</div><div class="table-wrap"><table class="small-table"><thead><tr>${labels.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(([s,v,token])=>`<tr><td>${esc(s)}</td><td class="mono ${tone(v)}">${units(v)}</td>${token!==undefined?`<td class="mono">${units(token)}</td>`:''}</tr>`).join('')}</tbody></table></div>`; }
function showDetail(id) {
  const row=state.rows.find(r=>r.id===id);if(!row)return;
  const c=row.calculation;
  let html=`<p class="detail-event">${esc(game(row.game_id)?.name)}</p><h3 class="detail-bet">${esc(betTitle(row))}</h3><p class="notice">Historical fixture calculation only. Quotes, phase and actionability are not verified.</p>`;
  if(row.kind==='positive_ev') {
    html+=metrics([['Conditional EV',percent(c.conditional_ev_ratio_on_capital,true)],['Capital at risk',units(c.capital_at_risk)],['Stake',units(c.stake)],['Conditional expected profit',units(c.conditional_expected_profit)],['Probability selection wins',percent(c.conditional_fair_probability)],['Unconditional EV','Not estimated']]);
    html+=`<h3>Probability basis</h3><p class="muted">Named selection wins given decisive settlement. For a lay, this is the chance the selection wins—not the chance the lay wins. Reference books are normalized separately, then equally weighted.</p><h3>Reference estimate</h3><div class="table-wrap"><table class="small-table"><thead><tr><th>Reference book</th><th>Selection probabilities</th></tr></thead><tbody>${c.reference_books.map(b=>`<tr><td>${esc(book(b.sportsbook_id))}</td><td>${b.probabilities.map(([s,p])=>`${esc(quote(b.quote_ids.find(q=>quote(q)?.selection_id===s))?.selection_name||s)}: ${percent(p)}`).join('<br>')}</td></tr>`).join('')}</tbody></table></div>`;
  } else if(row.kind==='middle') {
    html+=metrics([['Capital required',units(row.capital_required)],['Worst modeled payoff',units(row.minimum_profit)],['Best modeled payoff',units(c.payoff.maximum_modeled_profit)],['Middle EV','Not estimated']]);
    html+=`<h3>Score-range payoffs</h3><p class="muted">Coordinate: ${c.coordinate==='home_minus_away'?'home score minus away score':'total points'}. No scoring probability model was supplied.</p>`+payoffTable(c.payoff.states.map(s=>[s.state_id==='common_refund'?'Common refund':s.state_id.replace('score:','').replace('-inf:', '≤ ').replace(':+inf',' or more').replaceAll(':','–'),s.net_profit]));
  } else {
    html+=metrics([['Capital required',units(row.capital_required)],['Decisive minimum',units(c.minimum_decisive_profit)],['All-modeled-state minimum',units(c.minimum_modeled_profit)],['Common refund',units(c.refund_profit)]]);
    const payoffs=c.legs?c.legs.map(l=>[selection(quote(l.quote_id)),l.profit_if_selection_wins]):[['Selection wins',c.profit_if_selection_wins],['Selection loses',c.profit_if_selection_loses]];
    if(c.refund_profit!==null)payoffs.push(['Common refund',c.refund_profit]);
    html+=`<h3>Payoff table</h3>`+payoffTable(payoffs);
    if(c.lay_stake)html+=metrics([['Back stake',units(c.back_stake)],['Lay stake',units(c.lay_stake)],['Lay liability',units(c.lay_liability)]]);
    if(c.legs)html+=`<h3>Rounded stake allocation</h3>${metrics(c.legs.map(l=>[`${book(l.sportsbook_id)} · ${selection(quote(l.quote_id))}`,units(l.stake)]))}`;
  }
  html+=`<h3>Exact source quotes</h3><div class="quote-evidence">${row.quote_ids.map(id=>{const q=quote(id);return `<div>${badge(q.sportsbook_id)}<span>${esc(selection(q))}</span><strong class="mono">${american(q.decimal_odds)}</strong></div>`;}).join('')}</div><p class="muted small-text">Observed ${esc(date(row.oldest_observed_at))}. Prices and calculations are fixture-bound, not currently actionable.</p><details class="raw"><summary>Inspect full calculation (raw decimal API values)</summary><pre>${esc(JSON.stringify(c,null,2))}</pre></details><button class="button secondary full" data-action="odds" data-id="${esc(row.game_id)}">Open this event’s odds board →</button>`;
  openDialog(TITLES[row.kind],'CALCULATION DETAILS',html);
}
function showOdds(id,market='') {
  const g=game(id);if(!g)return;
  const quotes=[...state.quotes.values()].filter(q=>q.game_id===id && (!market||q.market_key===market));
  const html=`<p class="detail-event">${esc(sport(g.sport_key))} · ${esc(date(g.starts_at))}</p><p class="notice">Phase unknown · Synthetic prices · Best quoted compares raw prices before commission.</p><label class="field board-select"><span>MARKET</span><select id="board-market" data-game="${esc(id)}">${options(g.market_keys.map(k=>[k,MARKETS[k]]),market,'All featured markets')}</select></label>${oddsMatrix(quotes,state.caps.books)}<p class="muted">Quotes observed ${esc(date(quotes[0]?.observed_at||state.meta.captured_at))}. Select a back quote to use it in the promo calculator.</p><button class="button secondary full" data-action="game-tools" data-id="${esc(id)}">See +EV for this event →</button>`;
  $('detail').classList.add('odds-dialog');
  if($('detail').open){$('detail-title').textContent=g.name;$('detail-eyebrow').textContent='EVENT ODDS BOARD';$('detail-body').innerHTML=html;}
  else openDialog(g.name,'EVENT ODDS BOARD',html);
}

function renderPromo() {
  $('view').innerHTML=`<div class="promo-layout"><section class="promo-form-card"><div class="section-title"><span class="step">01</span><div><h2>Build a conversion</h2><p>Start with exact quotes from the current fixture.</p></div></div>
    <form id="promo-form"><div class="form-grid"><label class="field"><span>EVENT</span><select id="promo-game" name="game">${options(state.games.map(g=>[g.id,g.name]),'demo-nba')}</select></label><label class="field"><span>EXACT CONTRACT</span><select id="promo-contract" name="contract"></select></label>
    <label class="field wide"><span>PROMO QUOTE · BACK</span><select id="promo-quote" name="promo_quote"></select></label><label class="field"><span>HEDGE TYPE</span><select id="hedge-type" name="hedge_type"><option value="lay">Same-selection lay</option><option value="opposite_back">Opposite back · two-way only</option></select></label><label class="field"><span>HEDGE QUOTE</span><select id="hedge-quote" name="hedge_quote"></select></label></div>
    <p id="hedge-help" class="inline-help"></p><div class="form-divider"></div><div class="section-title small-section"><span class="step">02</span><div><h2>Define the promo</h2><p>Assumed terms, not verified eligibility.</p></div></div>
    <div class="form-grid"><label class="field wide"><span>PROMO TYPE</span><select id="promo-kind" name="kind"><option value="bonus_stake_not_returned">Bonus bet · stake not returned</option><option value="bonus_stake_returned_as_cash">Bonus bet · stake returned as cash</option><option value="loss_refund_cash">Cash wager · loss refunded as cash</option><option value="loss_refund_bonus">Cash wager · loss refunded as bonus token</option></select></label>
    ${moneyField('face_value','FACE VALUE / STAKE (USD)','100.00')}${moneyField('eligible_stake_cap','ELIGIBLE STAKE CAP','100.00')}<label class="field"><span>MINIMUM AMERICAN ODDS</span><input name="minimum_american_odds" value="-200" required maxlength="10" autocomplete="off" aria-describedby="american-help"></label>${moneyField('loss_refund_cap','LOSS REFUND CAP','0.00')}${moneyField('stake_increment','STAKE INCREMENT','0.01')}${moneyField('maximum_hedge_stake','MAX. HEDGE STAKE (OPTIONAL)','',false)}${moneyField('maximum_lay_liability','MAX. LAY LIABILITY (OPTIONAL)','',false)}
    <label class="check-field wide"><input type="checkbox" name="bonus_restored_on_void" id="restore-bonus" checked> Restore the bonus token on a common void</label></div>
    <p id="american-help" class="inline-help">Use signed odds such as -200 or +150. Minimum thresholds convert upward to 12 decimal places when needed.</p><p class="notice">Amounts display in USD ($1 per calculation unit). Bonus token face remains separate from cash profit.</p><button class="button full calculate" type="submit" id="calculate">Calculate conversion <span aria-hidden="true">→</span></button><p class="small-text muted">This runs a calculation only. No bet is placed or saved.</p></form></section>
    <section id="promo-output" class="promo-result" aria-live="polite">${promoPlaceholder()}</section></div>`;
  syncPromo();syncKind();
}
function moneyField(name,label,value,required=true){return `<label class="field money-field"><span>${label}</span><span class="money-input"><span aria-hidden="true">$</span><input name="${name}" value="${value}" inputmode="decimal" maxlength="26" ${required?'required':''} pattern="(0|[1-9][0-9]{0,12})(\\.[0-9]{1,12})?" autocomplete="off"></span></label>`;}
function promoPlaceholder(){return `<div class="result-placeholder"><div class="result-graphic" aria-hidden="true">◇</div><p class="eyebrow">UNDERSTAND THE TRADE-OFF</p><h2>Every outcome, accounted for.</h2><p>Your hedge, cash requirement and payoff table will appear here. A refunded token is not cash profit.</p><div class="placeholder-lines"><span></span><span></span><span></span></div></div>`;}
function replaceOptions(id,items,desired) {const select=$(id),old=desired??select.value;select.innerHTML=options(items,old);if(items.some(([key])=>key===old))select.value=old;}
function syncPromo(desiredQuote) {
  const chosen=desiredQuote?quote(desiredQuote):null;if(chosen)$('promo-game').value=chosen.game_id;
  const quotes=[...state.quotes.values()].filter(q=>q.game_id===$('promo-game').value);
  const contracts=[...new Map(quotes.filter(q=>!q.market_key.endsWith('_lay')).map(q=>[q.contract_id,`${MARKETS[q.market_key]} · ${q.contract_id}`])).entries()];
  replaceOptions('promo-contract',contracts,chosen?.contract_id);
  const backs=quotes.filter(q=>q.contract_id===$('promo-contract').value&&!q.market_key.endsWith('_lay')&&/^0(?:\.0*)?$/.test(q.commission_rate));
  replaceOptions('promo-quote',backs.map(q=>[q.id,`${book(q.sportsbook_id)} · ${selection(q)} @ ${american(q.decimal_odds)}`]),chosen?.id);
  const candidates=eligibleHedges(quotes,quote($('promo-quote').value),$('hedge-type').value);
  replaceOptions('hedge-quote',candidates.map(q=>[q.id,`${book(q.sportsbook_id)} · ${selection(q)} @ ${american(q.decimal_odds)}`]));
  $('calculate').disabled=!candidates.length;
  $('hedge-help').textContent=candidates.length?'Exact contract matched. Different books. Current availability remains unverified.':'No compatible hedge in this fixture. Try a lay or a different contract. A single opposite back cannot cover a draw or multi-entrant market.';
  const cap=$('promo-form').elements.maximum_lay_liability;cap.disabled=$('hedge-type').value!=='lay';
}
function syncKind() {
  const form=$('promo-form'),bonus=$('promo-kind').value.startsWith('bonus_');
  form.elements.loss_refund_cap.disabled=bonus;if(bonus)form.elements.loss_refund_cap.value='0.00';else if(/^0(?:\.0*)?$/.test(form.elements.loss_refund_cap.value))form.elements.loss_refund_cap.value=form.elements.face_value.value;
  form.elements.bonus_restored_on_void.disabled=!bonus;form.elements.bonus_restored_on_void.checked=bonus;
}
function invalidatePromo() {promoController?.abort();if($('promo-output'))$('promo-output').innerHTML=promoPlaceholder();if($('calculate'))$('calculate').textContent='Calculate conversion →';}
async function calculatePromo(form) {
  if(!form.reportValidity())return;
  const values=Object.fromEntries(new FormData(form));
  try{values.minimum_decimal_odds=americanToDecimal(values.minimum_american_odds);}catch(error){form.elements.minimum_american_odds.setCustomValidity(error.message);form.elements.minimum_american_odds.reportValidity();return;}
  for(const [key,value] of Object.entries(values))if(['face_value','eligible_stake_cap','minimum_decimal_odds','loss_refund_cap','stake_increment','maximum_hedge_stake','maximum_lay_liability'].includes(key)&&value&&!decimalInput(value)){form.elements[key].setCustomValidity('Use a decimal string with up to 12 decimal places.');form.elements[key].reportValidity();return;}
  const bonus=values.kind.startsWith('bonus_');
  const command={snapshot_id:state.meta.snapshot_id,contract_id:values.contract,promo_quote_id:values.promo_quote,hedge_quote_id:values.hedge_quote,hedge_type:values.hedge_type,stake_increment:values.stake_increment,
    terms:{terms_id:'fixture:frontend-scenario/1',kind:values.kind,face_value:values.face_value,eligible_stake_cap:values.eligible_stake_cap,minimum_decimal_odds:values.minimum_decimal_odds,loss_refund_cap:bonus?'0':values.loss_refund_cap,eligibility_evidence_id:'fixture:user-assumed-eligibility',bonus_restored_on_void:bonus&&form.elements.bonus_restored_on_void.checked}};
  if(values.maximum_hedge_stake)command.maximum_hedge_stake=values.maximum_hedge_stake;
  if(values.hedge_type==='lay'&&values.maximum_lay_liability)command.maximum_lay_liability=values.maximum_lay_liability;
  promoController?.abort();promoController=new AbortController();const signal=promoController.signal;
  $('calculate').disabled=true;$('calculate').textContent='Calculating…';$('promo-output').innerHTML=spinner('Calculating the frozen quote scenario…');
  try {
    const result=await request('calculators/promo',{body:command,signal,snapshot:state.meta.snapshot_id});if(signal.aborted||state.view!=='promo')return;
    const c=result.data.calculation;
    $('promo-output').innerHTML=`<div class="conversion-head"><span class="fixture-badge">FIXTURE CALCULATION</span><p>Minimum decisive cash profit</p><strong class="${tone(c.minimum_decisive_cash_profit)}">${units(c.minimum_decisive_cash_profit)}</strong><small>${percent(c.decisive_cash_to_face_ratio)} of promo face value · not unconditional EV</small></div><div class="conversion-body">${metrics([['Hedge stake',units(c.lay_stake??c.hedge_stake)],...(c.lay_liability!==undefined?[['Lay liability',units(c.lay_liability)]]:[]),['Upfront cash required',units(c.upfront_cash_required)],['All-modeled-state minimum',units(c.minimum_modeled_cash_profit)]])}<h3>What happens in each outcome</h3>${payoffTable(c.outcomes.map(o=>[({selection_wins:'Selection wins',selection_loses:'Selection loses',common_void:'Common void'})[o.state]||o.state,o.net_cash_profit,o.noncash_bonus_face_returned]),['Outcome','Cash profit','Noncash face'])}<p class="notice">Noncash face is not included in profit. Eligibility and quote availability are unverified. A common void may yield no cash profit.</p><details class="raw"><summary>Inspect full calculation</summary><pre>${esc(JSON.stringify(c,null,2))}</pre></details></div>`;
  } catch(error){if(error.name!=='AbortError'&&!signal.aborted)$('promo-output').innerHTML=message(error,'recalculate');}
  finally{if(!signal.aborted&&$('calculate')){$('calculate').disabled=false;$('calculate').textContent='Calculate conversion →';}}
}

document.addEventListener('submit',event=>{
  if(event.target.id==='filters') {
    event.preventDefault();const values=Object.fromEntries(new FormData(event.target));
    if(values.threshold && (!decimalInput(values.threshold)||values.threshold.split('.')[1]?.length>10)) {const input=event.target.elements.threshold;input.setCustomValidity('Use a nonnegative percentage with at most 10 decimal places.');input.reportValidity();return;}
    state.filters={...values,sort:$('sort').value};state.offset=0;if(matchMedia('(max-width:600px)').matches)$('filter-disclosure').open=false;loadPage();
  } else if(event.target.id==='promo-form'){event.preventDefault();calculatePromo(event.target);}
});
document.addEventListener('input',event=>{
  event.target.setCustomValidity?.('');
  if(event.target.closest('#promo-form')){invalidatePromo();syncPromo();}
});
document.addEventListener('change',event=>{
  if(event.target.id==='sort'){state.filters.sort=event.target.value;state.offset=0;loadPage();}
  if(event.target.id==='page-size'){state.limit=Number(event.target.value);state.offset=0;loadPage();}
  if(event.target.id==='board-market')showOdds(event.target.dataset.game,event.target.value);
  if(event.target.closest('#promo-form')){invalidatePromo();if(event.target.id==='promo-kind')syncKind();syncPromo();}
});
document.addEventListener('click',event=>{
  if(event.target.closest('.skip')){event.preventDefault();$('main').focus();$('main').scrollIntoView();return;}
  const button=event.target.closest('[data-action]');if(!button)return;const {action,id}=button.dataset;
  if(action==='reload'){bootstrap();return;}
  if(action==='clear-filters'){state.filters={};state.offset=0;renderView();}
  if(action==='retry-page')loadPage();
  if(action==='previous'){state.offset=Math.max(0,state.offset-state.limit);loadPage();}
  if(action==='next'&&state.page?.next_offset!==null){state.offset=state.page.next_offset;loadPage();}
  if(action==='detail')showDetail(id);
  if(action==='odds')showOdds(id);
  if(action==='recalculate')$('promo-form')?.requestSubmit();
  if(action==='use-promo'){pendingPromoQuote=id;if(location.hash==='#promo')navigate();else location.hash='promo';}
  if(action==='game-tools'){pendingGame=id;if(location.hash==='#positive_ev')navigate();else location.hash='positive_ev';}
});
$('refresh').addEventListener('click',bootstrap);
$('close-detail').addEventListener('click',()=>$('detail').close());
$('detail').addEventListener('click',event=>{if(event.target===$('detail')){const r=$('detail').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('detail').close();}});
window.addEventListener('hashchange',()=>navigate());
matchMedia('(max-width:600px)').addEventListener('change',event=>{if($('filter-disclosure'))$('filter-disclosure').open=!event.matches;});
window.addEventListener('pagehide',()=>{bootController?.abort();pageController?.abort();promoController?.abort();});
navigate();bootstrap();
