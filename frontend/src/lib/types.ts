// ── Market Data ──
export interface MarketData {
  symbol: string;
  bid: number;
  ask: number;
  ltp: number;
  volume: number;
  day_volume: number;
  volatility: number;
  avg_trade_size: number;
  open: number;
  high: number;
  low: number;
  change_pct: number;
  time_to_close: number;
  spread: number;
  spread_bps: number;
  timestamp: string;
}

// ── Instruments ──
export interface Instrument {
  symbol: string;
  name: string;
  exchange: string;
  lot_size: number;
  tick_size: number;
  circuit_limit_pct: number;
  adv: number;
  sector: string;
  is_active: number;
}

// ── Clients ──
export interface Client {
  client_id: string;
  name: string;
  credit_limit: number;
  position_limit: number;
  restricted_symbols: string;
  notes: string;
  risk_aversion: number;
  is_active: number;
  created_at: string;
}

// ── Orders ──
export type Direction = "BUY" | "SELL";
export type OrderType = "MARKET" | "LIMIT" | "STOP_LOSS";
export type AlgoType = "NONE" | "POV" | "VWAP" | "ICEBERG";
export type TIF = "GFD" | "IOC" | "FOK" | "GTC" | "GTD";
export type Capacity = "AGENCY" | "PRINCIPAL" | "RISKLESS_PRINCIPAL" | "MIXED";
export type OrderStatus =
  | "PENDING"
  | "VALIDATED"
  | "WORKING"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "EXPIRED";

export interface AlgoParams {
  // POV
  target_participation_rate?: number;
  min_order_size?: number;
  max_order_size?: number;
  // VWAP
  volume_curve?: string;
  max_volume_pct?: number;
  // ICEBERG
  display_quantity?: number;
  // Common
  aggression_level?: string;
}

export interface Order {
  order_id: string;
  parent_order_id: string | null;
  client_id: string;
  account_id: string | null;
  symbol: string;
  direction: Direction;
  order_type: OrderType;
  quantity: number;
  filled_quantity: number;
  limit_price: number | null;
  stop_price: number | null;
  algo_type: AlgoType;
  algo_params: string; // JSON string
  start_time: string | null;
  end_time: string | null;
  tif: TIF;
  urgency: number;
  get_done: number;
  capacity: Capacity;
  order_notes: string;
  status: OrderStatus;
  avg_fill_price: number;
  created_at: string;
  updated_at: string;
}

export interface Execution {
  execution_id: string;
  order_id: string;
  fill_price: number;
  fill_quantity: number;
  venue: string;
  executed_at: string;
}

export interface OrderHistory {
  id: number;
  order_id: string;
  action: string;
  details: string;
  created_at: string;
}

export interface OrderDetail {
  order: Order;
  executions: Execution[];
  history: OrderHistory[];
  child_orders: Order[];
}

// ── Create Order Request ──
export interface CreateOrderRequest {
  client_id: string;
  symbol: string;
  direction: Direction;
  order_type: OrderType;
  quantity: number;
  limit_price?: number | null;
  stop_price?: number | null;
  algo_type?: AlgoType;
  algo_params?: AlgoParams;
  account_id?: string;
  start_time?: string;
  end_time?: string;
  tif?: TIF;
  urgency?: number;
  get_done?: boolean;
  capacity?: Capacity;
  order_notes?: string;
}

// ── Prefill ──
export interface PrefillRequest {
  client_id: string;
  symbol: string;
  direction: string;
  quantity?: number;
  urgency?: number;        // 0-100, undefined = auto-compute
  order_notes?: string;    // free-text for NLP parsing
}

export interface PrefillResponse {
  suggestions: Record<string, string | boolean>;
  explanations: Record<string, string>;
  confidence: Record<string, number>;
  urgency_score: number;
  computed_urgency: number;
  scenario_tag: string;
  scenario_label: string;
  why_not: Record<string, string>;
}

// ── Analytics ──
export interface Candlestick {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface MarketDataRow {
  id: number;
  symbol: string;
  bid: number;
  ask: number;
  ltp: number;
  volume: number;
  volatility: number;
  avg_trade_size: number;
  timestamp: string;
}

// ── Rule Config ──
export interface RuleConfigItem {
  id: number;
  category: string;
  key: string;
  value: number;
  label: string;
  description: string;
  data_type: string;
  min_value: number | null;
  max_value: number | null;
  unit: string;
  display_order: number;
  updated_at: string;
}

// ── Accounts ──
export interface Account {
  account_id: string;
  client_id: string;
  account_name: string;
  account_type: string;
  is_default: number;
  is_active: number;
  created_at: string;
}
