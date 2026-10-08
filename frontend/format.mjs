// Exact base-10 display operations. Never round-trip analytical values through Number.
export const MARKETS = {h2h:'Moneyline',spreads:'Spreads',totals:'Totals',outrights:'Outrights',h2h_lay:'Moneyline · Lay',outrights_lay:'Outrights · Lay'};
export const TITLES = {positive_ev:'Positive EV',arbitrage:'Arbitrage',middle:'Middles',props:'Player props',games:'Schedule',promo:'Promo converter'};
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function parts(value) {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value));
  if (!match || String(value).length > 120) throw new Error('Invalid decimal value');
  return {negative:match[1] === '-', digits:BigInt(match[2] + (match[3] || '')), places:(match[3] || '').length};
}
export function shiftDecimal(value, shift) {
  const p = parts(value); let scale = p.places - shift; let digits = p.digits.toString();
  if (scale < 0) { digits += '0'.repeat(-scale); scale = 0; }
  digits = digits.padStart(scale + 1, '0');
  let result = scale ? digits.slice(0, -scale) + '.' + digits.slice(-scale) : digits;
  if (result.includes('.')) result = result.replace(/0+$/, '').replace(/\.$/, '');
  return (p.negative && p.digits !== 0n ? '-' : '') + result;
}
export function fixed(value, places=2) {
  if (value === null || value === undefined) return '—';
  const p = parts(value); let digits = p.digits;
  if (p.places > places) { const divisor = 10n ** BigInt(p.places - places); digits = (digits + divisor / 2n) / divisor; }
  else digits *= 10n ** BigInt(places - p.places);
  const text = digits.toString().padStart(places + 1, '0');
  return (p.negative && digits !== 0n ? '-' : '') + (places ? text.slice(0,-places) + '.' + text.slice(-places) : text);
}
export const percent = (value, signed=false) => value == null ? '—' : `${signed && !String(value).startsWith('-') && parts(value).digits !== 0n ? '+' : ''}${fixed(shiftDecimal(value,2))}%`;
export const units = value => value == null ? '—' : `${fixed(value)} u`;
export function usd(value) {
  if (value == null) return '—';
  const rounded = fixed(value), negative = rounded.startsWith('-');
  const [whole, fraction] = rounded.replace(/^-/, '').split('.');
  return `${negative ? '-' : ''}$${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction}`;
}
export function compareDecimal(a, b) {
  const x=parts(a), y=parts(b), places=Math.max(x.places,y.places);
  const left=x.digits*10n**BigInt(places-x.places)*(x.negative?-1n:1n);
  const right=y.digits*10n**BigInt(places-y.places)*(y.negative?-1n:1n);
  return left < right ? -1 : left > right ? 1 : 0;
}
export function american(value) {
  if (value == null) return '—';
  const p=parts(value), scale=10n**BigInt(p.places), profit=p.digits-scale;
  if(p.negative || profit<=0n)throw new Error('Decimal odds must exceed one');
  const positive=profit>=scale;
  const numerator=100n*(positive?profit:scale), denominator=positive?scale:profit;
  const rounded=(numerator*2n+denominator)/(2n*denominator);
  return `${positive?'+':'-'}${rounded}`;
}
// Minimum thresholds round upward at the API's supported precision.
export function americanToDecimal(value) {
  if(!/^[+-]\d{3,9}$/.test(value) || BigInt(value.replace(/^[+-]/,''))<100n)
    throw new Error('Use signed American odds, such as +150 or -200, with magnitude at least 100.');
  const amount=BigInt(value.slice(1)), scale=10n**12n;
  const numerator=value[0]==='+'?amount:100n, denominator=value[0]==='+'?100n:amount;
  const result=scale+(numerator*scale+denominator-1n)/denominator;
  const text=result.toString().padStart(13,'0');
  return `${text.slice(0,-12)}.${text.slice(-12)}`.replace(/0+$/,'').replace(/\.$/,'');
}
export const tone = value => value != null && String(value).startsWith('-') && parts(value).digits !== 0n ? 'negative' : 'positive';
export function point(value) { return value == null ? '' : (parts(value).negative ? '' : '+') + shiftDecimal(value,0); }
export function selection(quote) {
  if (!quote) return 'Selection unavailable';
  return quote.selection_name + (quote.point == null ? '' : ` ${quote.market_key === 'spreads' ? point(quote.point) : shiftDecimal(quote.point,0)}`) + (quote.market_key.endsWith('_lay') ? ' · Lay' : '');
}
export function date(value) { return new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/Chicago',timeZoneName:'short'}).format(new Date(value)); }
export function sport(value) { return ({basketball_nba:'Basketball · NBA',soccer_demo:'Soccer',golf_demo_winner:'Golf · Outrights'})[value] || value; }
export function decimalInput(value) { return /^(0|[1-9]\d{0,12})(\.\d{1,12})?$/.test(value); }

export function eligibleHedges(quotes, promo, type) {
  if (!promo) return [];
  const contract = quotes.filter(q=>q.contract_id===promo.contract_id);
  if (type === 'opposite_back' && new Set(contract.filter(q=>!q.market_key.endsWith('_lay')).map(q=>q.selection_id)).size !== 2) return [];
  return contract.filter(q=>q.sportsbook_id!==promo.sportsbook_id && (type==='lay'
    ? q.market_key===`${promo.market_key}_lay` && q.selection_id===promo.selection_id
    : q.market_key===promo.market_key && q.selection_id!==promo.selection_id));
}

function build(negative, digits, places) {
  const text = digits.toString().padStart(places + 1, '0');
  let result = places ? text.slice(0, -places) + '.' + text.slice(-places) : text;
  if (result.includes('.')) result = result.replace(/0+$/, '').replace(/\.$/, '');
  return (negative && digits !== 0n ? '-' : '') + result;
}
// Exact decimal product, used to scale a calculation linearly to the user's stake.
export function mulDecimal(a, b) {
  const x = parts(a), y = parts(b);
  return build(x.negative !== y.negative, x.digits * y.digits, x.places + y.places);
}
// Exact decimal quotient rounded half-up to `places`.
export function divDecimal(a, b, places = 10) {
  const x = parts(a), y = parts(b);
  if (y.digits === 0n) throw new Error('Division by zero');
  const numerator = x.digits * 10n ** BigInt(y.places + places), denominator = y.digits * 10n ** BigInt(x.places);
  return build(x.negative !== y.negative, (numerator * 2n + denominator) / (2n * denominator), places);
}
export function ageLabel(value, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  return seconds < 90 ? `${seconds}s ago` : seconds < 5400 ? `${Math.round(seconds / 60)}m ago` : `${Math.round(seconds / 3600)}h ago`;
}
export function subDecimal(a, b) {
  const x = parts(a), y = parts(b), places = Math.max(x.places, y.places);
  const left = x.digits * 10n ** BigInt(places - x.places) * (x.negative ? -1n : 1n);
  const right = y.digits * 10n ** BigInt(places - y.places) * (y.negative ? -1n : 1n);
  const diff = left - right;
  return build(diff < 0n, diff < 0n ? -diff : diff, places);
}
