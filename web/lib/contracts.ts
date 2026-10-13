import type { QuoteLinks } from "./bet-links";
export type DecimalText = string;
export type MarketKey =
  "h2h" | "spreads" | "totals" | "outrights" | "h2h_lay" | "outrights_lay";
export type ToolKind = "positive_ev" | "arbitrage" | "middle";
export type View = ToolKind | "games" | "promo" | "props";
export interface Meta {
  format: "corner.product_api/1";
  data_mode: "fixture" | "database";
  snapshot_id: string;
  captured_at: string;
  production_authorized: false;
  availability_verified: false;
}
export interface Envelope<T> {
  meta: Meta;
  data: T;
}
export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  next_offset: number | null;
}
export interface Book {
  id: string;
  name: string;
  commission: DecimalText;
}
export interface Capabilities {
  market_keys: MarketKey[];
  tools: ToolKind[];
  books: Book[];
  sports: string[];
}
export interface Game {
  id: string;
  sport_key: string;
  competition: string;
  name: string;
  starts_at: string;
  scope: "full_game" | "competition";
  market_keys: MarketKey[];
  quote_count: number;
  phase: "unknown";
}
export interface Quote {
  id: string;
  game_id: string;
  contract_id: string;
  market_key: MarketKey;
  sportsbook_id: string;
  selection_id: string;
  selection_name: string;
  side: string;
  point: DecimalText | null;
  decimal_odds: DecimalText;
  commission_rate: DecimalText;
  observed_at: string;
  // Sportsbook links (event, market, betslip) when the provider gave valid ones.
  links?: QuoteLinks | null;
}
export interface Leg {
  quote_id: string;
  stake: DecimalText;
  profit_if_selection_wins?: DecimalText;
}
export interface FeaturedEV {
  format: "corner.featured_ev/1";
  target_quote_id: string;
  stake: DecimalText;
  capital_at_risk: DecimalText;
  conditional_expected_profit: DecimalText;
  conditional_fair_probability: DecimalText;
  conditional_ev_ratio_on_capital: DecimalText;
  reference_books: {
    sportsbook_id: string;
    probabilities: [string, DecimalText][];
    quote_ids: string[];
    weight?: DecimalText;
  }[];
}
export interface Cover {
  legs: (Leg & { profit_if_selection_wins: DecimalText })[];
  minimum_decisive_profit: DecimalText;
  minimum_modeled_profit: DecimalText;
  refund_profit: DecimalText | null;
}
export interface BackLay {
  back_quote_id: string;
  lay_quote_id: string;
  back_stake: DecimalText;
  lay_stake: DecimalText;
  lay_liability: DecimalText;
  minimum_decisive_profit: DecimalText;
  minimum_modeled_profit: DecimalText;
  refund_profit: DecimalText | null;
  profit_if_selection_wins: DecimalText;
  profit_if_selection_loses: DecimalText;
}
export interface Middle {
  legs: Leg[];
  coordinate: string;
  double_win_ranges: [number | null, number | null][];
  payoff: {
    maximum_modeled_profit: DecimalText;
    states: { state_id: string; net_profit: DecimalText }[];
  };
}
interface RowBase {
  id: string;
  game_id: string;
  contract_id: string;
  market_key: MarketKey;
  quote_ids: string[];
  capital_required: DecimalText;
  minimum_profit: DecimalText | null;
  conditional_ev_ratio: DecimalText | null;
  oldest_observed_at: string;
}
export type ToolRow = RowBase &
  (
    | { kind: "positive_ev"; calculation: FeaturedEV }
    | { kind: "middle"; calculation: Middle }
    | { kind: "arbitrage"; calculation: Cover | BackLay }
  );
export type PromoKind =
  | "bonus_stake_not_returned"
  | "bonus_stake_returned_as_cash"
  | "loss_refund_cash"
  | "loss_refund_bonus";
export interface PromoCommand {
  snapshot_id: string;
  contract_id: string;
  promo_quote_id: string;
  hedge_quote_id: string;
  hedge_type: "lay" | "opposite_back";
  stake_increment: DecimalText;
  maximum_hedge_stake?: DecimalText;
  maximum_lay_liability?: DecimalText;
  terms: {
    terms_id: string;
    kind: PromoKind;
    face_value: DecimalText;
    eligible_stake_cap: DecimalText;
    minimum_decimal_odds: DecimalText;
    loss_refund_cap: DecimalText;
    eligibility_evidence_id: string;
    bonus_restored_on_void: boolean;
  };
}
export interface PromoResult {
  id: string;
  calculation: {
    minimum_decisive_cash_profit: DecimalText;
    minimum_modeled_cash_profit: DecimalText;
    decisive_cash_to_face_ratio: DecimalText;
    lay_stake?: DecimalText;
    hedge_stake?: DecimalText;
    lay_liability?: DecimalText;
    upfront_cash_required: DecimalText;
    outcomes: {
      state: string;
      net_cash_profit: DecimalText;
      noncash_bonus_face_returned: DecimalText;
    }[];
  };
}
export const VIEWS: View[] = [
  "positive_ev",
  "arbitrage",
  "middle",
  "props",
  "games",
  "promo",
];
