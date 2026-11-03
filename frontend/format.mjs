// Exact base-10 display operations. Never round-trip analytical values through Number.
/** @type {Record<string, string>} */
export const MARKETS = {alternate_team_totals:'Alternate team totals',alternate_spreads:'Alternate spreads',alternate_totals:'Alternate totals',btts:'Both teams to score',draw_no_bet:'Draw no bet',team_totals:'Team totals',h2h:'Moneyline',spreads:'Spreads',totals:'Totals',outrights:'Outrights',h2h_lay:'Moneyline · Lay',outrights_lay:'Outrights · Lay',...{"player_points": "Points", "player_points_q1": "1st Quarter Points", "player_threes": "Made Threes", "player_rebounds": "Rebounds", "player_rebounds_q1": "1st Quarter Rebounds", "player_assists": "Assists", "player_assists_q1": "1st Quarter Assists", "player_blocks": "Blocks", "player_steals": "Steals", "player_turnovers": "Turnovers", "player_points_rebounds_assists": "Points + Rebounds + Assists", "player_points_assists": "Points + Assists", "player_points_rebounds": "Points + Rebounds", "player_rebounds_assists": "Rebounds + Assists", "player_double_double": "Double-Double", "player_triple_double": "Triple-Double", "player_pass_yds": "Passing Yards", "player_pass_tds": "Passing TDs", "player_pass_completions": "Pass Completions", "player_pass_attempts": "Pass Attempts", "player_pass_interceptions": "Interceptions Thrown", "player_pass_longest_completion": "Longest Completion", "player_rush_yds": "Rushing Yards", "player_rush_attempts": "Rush Attempts", "player_rush_longest": "Longest Rush", "player_receptions": "Receptions", "player_reception_yds": "Receiving Yards", "player_reception_longest": "Longest Reception", "player_kicking_points": "Kicking Points", "player_field_goals": "Field Goals Made", "player_anytime_td": "Anytime TD Scorer", "player_1st_td": "First TD Scorer", "player_last_td": "Last TD Scorer", "player_tackles_assists": "Tackles + Assists", "player_solo_tackles": "Solo Tackles", "player_sacks": "Sacks", "batter_hits": "Batter Hits", "batter_runs_scored": "Batter Runs Scored", "batter_rbis": "Batter RBIs", "batter_home_runs": "Batter Home Runs", "batter_total_bases": "Batter Total Bases", "batter_singles": "Batter Singles", "batter_doubles": "Batter Doubles", "batter_triples": "Batter Triples", "batter_walks": "Batter Walks", "batter_stolen_bases": "Stolen Bases", "batter_hits_runs_rbis": "Hits + Runs + RBIs", "pitcher_strikeouts": "Pitcher Strikeouts", "pitcher_hits_allowed": "Pitcher Hits Allowed", "pitcher_earned_runs": "Pitcher Earned Runs", "pitcher_walks": "Pitcher Walks", "pitcher_outs": "Pitcher Outs Recorded", "pitcher_record_a_win": "Pitcher to Record a Win", "player_goals": "Goals", "player_shots_on_goal": "Shots on Goal", "player_power_play_points": "Power Play Points", "player_blocked_shots": "Blocked Shots", "player_total_saves": "Goalie Saves", "player_goal_scorer_anytime": "Anytime Goal Scorer", "player_goal_scorer_first": "First Goal Scorer", "player_goal_scorer_last": "Last Goal Scorer", "player_first_goal_scorer": "First Goal Scorer", "player_last_goal_scorer": "Last Goal Scorer", "player_shots": "Shots", "player_shots_on_target": "Shots on Target", "player_to_receive_card": "To Receive a Card", "player_to_receive_red_card": "To Receive a Red Card", "player_pass_rush_yds": "Pass + Rush Yards", "player_pass_rush_reception_tds": "Pass + Rush + Reception TDs", "player_pass_rush_reception_yds": "Pass + Rush + Reception Yards", "player_pats": "Extra Points", "player_reception_tds": "Receiving TDs", "player_rush_reception_tds": "Rush + Reception TDs", "player_rush_reception_yds": "Rush + Reception Yards", "player_rush_tds": "Rushing TDs", "batter_strikeouts": "Batter Strikeouts", "player_points_alternate": "Alternate Points", "player_rebounds_alternate": "Alternate Rebounds", "player_assists_alternate": "Alternate Assists", "player_blocks_alternate": "Alternate Blocks", "player_steals_alternate": "Alternate Steals", "player_turnovers_alternate": "Alternate Turnovers", "player_threes_alternate": "Alternate Made Threes", "player_points_assists_alternate": "Alternate Points + Assists", "player_points_rebounds_alternate": "Alternate Points + Rebounds", "player_rebounds_assists_alternate": "Alternate Rebounds + Assists", "player_points_rebounds_assists_alternate": "Alternate Points + Rebounds + Assists", "player_field_goals_alternate": "Alternate Field Goals Made", "player_kicking_points_alternate": "Alternate Kicking Points", "player_pass_attempts_alternate": "Alternate Pass Attempts", "player_pass_completions_alternate": "Alternate Pass Completions", "player_pass_interceptions_alternate": "Alternate Interceptions Thrown", "player_pass_longest_completion_alternate": "Alternate Longest Completion", "player_pass_rush_yds_alternate": "Alternate Pass + Rush Yards", "player_pass_rush_reception_tds_alternate": "Alternate Pass + Rush + Reception TDs", "player_pass_rush_reception_yds_alternate": "Alternate Pass + Rush + Reception Yards", "player_pass_tds_alternate": "Alternate Passing TDs", "player_pass_yds_alternate": "Alternate Passing Yards", "player_pats_alternate": "Alternate Extra Points", "player_receptions_alternate": "Alternate Receptions", "player_reception_longest_alternate": "Alternate Longest Reception", "player_reception_tds_alternate": "Alternate Receiving TDs", "player_reception_yds_alternate": "Alternate Receiving Yards", "player_rush_attempts_alternate": "Alternate Rush Attempts", "player_rush_longest_alternate": "Alternate Longest Rush", "player_rush_reception_tds_alternate": "Alternate Rush + Reception TDs", "player_rush_reception_yds_alternate": "Alternate Rush + Reception Yards", "player_rush_tds_alternate": "Alternate Rushing TDs", "player_rush_yds_alternate": "Alternate Rushing Yards", "player_sacks_alternate": "Alternate Sacks", "player_solo_tackles_alternate": "Alternate Solo Tackles", "player_tackles_assists_alternate": "Alternate Tackles + Assists", "batter_total_bases_alternate": "Alternate Batter Total Bases", "batter_home_runs_alternate": "Alternate Batter Home Runs", "batter_hits_alternate": "Alternate Batter Hits", "batter_rbis_alternate": "Alternate Batter RBIs", "batter_walks_alternate": "Alternate Batter Walks", "batter_strikeouts_alternate": "Alternate Batter Strikeouts", "batter_runs_scored_alternate": "Alternate Batter Runs Scored", "batter_hits_runs_rbis_alternate": "Alternate Hits + Runs + RBIs", "batter_singles_alternate": "Alternate Batter Singles", "batter_doubles_alternate": "Alternate Batter Doubles", "batter_triples_alternate": "Alternate Batter Triples", "pitcher_hits_allowed_alternate": "Alternate Pitcher Hits Allowed", "pitcher_walks_alternate": "Alternate Pitcher Walks", "pitcher_earned_runs_alternate": "Alternate Pitcher Earned Runs", "pitcher_strikeouts_alternate": "Alternate Pitcher Strikeouts", "pitcher_outs_alternate": "Alternate Pitcher Outs Recorded", "player_power_play_points_alternate": "Alternate Power Play Points", "player_goals_alternate": "Alternate Goals", "player_shots_on_goal_alternate": "Alternate Shots on Goal", "player_blocked_shots_alternate": "Alternate Blocked Shots", "player_total_saves_alternate": "Alternate Goalie Saves", "player_shots_alternate": "Alternate Shots", "player_shots_on_target_alternate": "Alternate Shots on Target"}};
export const TITLES = {positive_ev:'Positive EV',arbitrage:'Arbitrage',middle:'Middles',props:'Player props',games:'Schedule',promo:'Promo converter'};
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function parts(value) {
  const text = String(value);
  const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(text);
  if (!match || text.length > 120) throw new Error('Invalid decimal value');
  let places = (match[3] || '').length - Number(match[4] || 0);
  if (Math.abs(places) > 120) throw new Error('Invalid decimal value');
  let digits = BigInt(match[2] + (match[3] || ''));
  if (places < 0) { digits *= 10n ** BigInt(-places); places = 0; }
  return {negative:match[1] === '-', digits, places};
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
  return quote.selection_name + (quote.point == null ? '' : ` ${['spreads','alternate_spreads'].includes(quote.market_key) ? point(quote.point) : shiftDecimal(quote.point,0)}`) + (quote.market_key.endsWith('_lay') ? ' · Lay' : '');
}
export function date(value) { return new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/Chicago',timeZoneName:'short'}).format(new Date(value)); }
export function sport(value) { return ({"americanfootball_nfl": "NFL", "americanfootball_ncaaf": "NCAAF", "basketball_nba": "NBA", "basketball_ncaab": "NCAAB (Men)", "basketball_wncaab": "NCAAB (Women)", "basketball_wnba": "WNBA", "baseball_mlb": "MLB", "icehockey_nhl": "NHL", "mma_mixed_martial_arts": "MMA", "tennis_atp": "Tennis (Men)", "tennis_wta": "Tennis (Women)", "soccer_usa_mls": "MLS", "soccer_epl": "Premier League", "soccer_spain_la_liga": "La Liga", "soccer_germany_bundesliga": "Bundesliga", "soccer_italy_serie_a": "Serie A", "soccer_france_ligue_one": "Ligue 1", "soccer_uefa_champs_league": "Champions League", "soccer_demo": "Soccer", "golf_demo_winner": "Golf \u00b7 Outrights"})[value] || value; }
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
