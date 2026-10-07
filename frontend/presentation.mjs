import {MARKETS,esc,percent,usd,american,selection,date,sport,tone,compareDecimal} from './format.mjs';

export function toolCards(rows,{game,quote,badge}) {
  return `<div class="opportunity-list">${rows.map(row=>{
    const c=row.calculation,g=game(row.game_id),ev=row.kind==='positive_ev',middle=row.kind==='middle';
    const legs=ev?[{quote_id:c.target_quote_id,stake:c.stake}]:c.legs||[
      {quote_id:c.back_quote_id,stake:c.back_stake},{quote_id:c.lay_quote_id,stake:c.lay_stake}];
    const metric=ev?percent(row.conditional_ev_ratio,true):usd(middle?c.payoff.maximum_modeled_profit:c.minimum_decisive_profit);
    const label=ev?'CONDITIONAL EV':middle?'BEST MODELED PAYOFF':'DECISIVE MIN. PROFIT';
    const window=c.double_win_ranges?.map(([a,b])=>`${a??'−∞'}–${b??'∞'}`).join(', ');
    return `<article class="opportunity-card">
      <div class="card-edge"><span class="metric-label">${label}</span><strong class="edge-value ${tone(ev?row.conditional_ev_ratio:middle?c.payoff.maximum_modeled_profit:c.minimum_decisive_profit)}">${metric}</strong>
        <span class="edge-secondary">${ev?`${percent(c.conditional_fair_probability)} selection win chance`:middle?`Double-win window <b>${esc(window)}</b>`:`Modeled minimum <b class="${tone(row.minimum_profit)}">${usd(row.minimum_profit)}</b>`}</span>
        <span class="capital-caption">${ev?'Example stake':'Capital required'} <b>${usd(ev?c.stake:row.capital_required)}</b></span>
      </div>
      <div class="card-event"><span class="event-sport">${esc(sport(g?.sport_key))}</span><strong>${esc(g?.name)}</strong><time>${esc(date(g?.starts_at))}</time><span class="market-chip">${esc(MARKETS[row.market_key])}</span></div>
      <div class="card-legs">${legs.map((l,i)=>{
        const q=quote(l.quote_id);return `<div class="bet-leg"><span class="leg-number">${i+1}</span><div class="leg-selection"><strong>${esc(selection(q))}</strong><small>${q?.market_key.endsWith('_lay')?'Lay stake':'Back stake'}${q?.commission_rate&&compareDecimal(q.commission_rate,'0')>0?` · ${percent(q.commission_rate)} commission`:''}</small></div>${badge(q?.sportsbook_id)}<span class="leg-stake">${usd(l.stake)}</span><span class="american-line">${american(q?.decimal_odds)}</span></div>`;
      }).join('')}${ev?'<span class="card-footnote">Stake shown is the calculation example; sizing is not available.</span>':middle?`<span class="card-footnote">Worst modeled payoff <b class="${tone(row.minimum_profit)}">${usd(row.minimum_profit)}</b> · Middle EV not estimated</span>`:`<span class="card-footnote">${c.lay_liability?`Lay liability ${usd(c.lay_liability)} · `:''}Common refund ${usd(c.refund_profit)} profit</span>`}</div>
      <button class="inspect-card" data-action="detail" data-id="${esc(row.id)}" aria-label="View calculation for ${esc(legs.map(l=>selection(quote(l.quote_id))).join(' / '))}">View payoffs <span aria-hidden="true">↗</span></button>
    </article>`;
  }).join('')}</div>`;
}

export function oddsMatrix(quotes,books) {
  const groups=new Map();
  for(const q of quotes){const key=JSON.stringify([q.contract_id,q.market_key,q.selection_id]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(q);}
  const ordered=[...groups.values()].sort((a,b)=>Object.keys(MARKETS).indexOf(a[0].market_key)-Object.keys(MARKETS).indexOf(b[0].market_key)||a[0].contract_id.localeCompare(b[0].contract_id)||selection(a[0]).localeCompare(selection(b[0])));
  return `<div class="table-wrap odds-scroll"><table class="odds-matrix"><caption class="sr-only">American odds by exact contract and sportsbook. Best quoted compares raw prices before commission.</caption><thead><tr><th scope="col">Selection / exact line</th><th scope="col">Best quoted</th>${books.map(b=>`<th scope="col"><span class="book-initial">${esc(b.name.replace('Demo ','').replace('Reference ','R').slice(0,3))}</span>${esc(b.name.replace('Demo ',''))}</th>`).join('')}</tr></thead><tbody>${ordered.map(rows=>{
    const first=rows[0],lay=first.market_key.endsWith('_lay');
    const best=rows.reduce((a,b)=>(compareDecimal(a.decimal_odds,b.decimal_odds)*(lay?-1:1)>=0?a:b));
    return `<tr><th scope="row"><strong>${esc(selection(first))}</strong><small>${esc(MARKETS[first.market_key])} · ${esc(first.contract_id)}</small></th><td class="best-line"><strong>${american(best.decimal_odds)}</strong><small>${esc(books.find(b=>b.id===best.sportsbook_id)?.name.replace('Demo ','')||best.sportsbook_id)}</small></td>${books.map(b=>{
      const q=rows.find(r=>r.sportsbook_id===b.id);if(!q)return '<td class="missing-line" aria-label="No quote">—</td>';
      const same=compareDecimal(q.decimal_odds,best.decimal_odds)===0;
      return `<td class="${same?'price-best':''}">${lay?`<span class="odds-cell"><strong>${american(q.decimal_odds)}</strong><small>Lay · ${percent(q.commission_rate)} fee</small></span>`:`<button class="odds-cell" data-action="use-promo" data-id="${esc(q.id)}" aria-label="Use ${esc(b.name)} ${esc(selection(q))} ${american(q.decimal_odds)} in promo"><strong>${american(q.decimal_odds)}</strong><small>Use in promo ↗</small></button>`}</td>`;
    }).join('')}</tr>`;
  }).join('')}</tbody></table></div>`;
}
