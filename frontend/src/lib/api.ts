import type {
  MarketData,
  Instrument,
  Client,
  Order,
  OrderDetail,
  CreateOrderRequest,
  PrefillRequest,
  PrefillResponse,
  Candlestick,
  PaginatedResponse,
  Execution,
  OrderHistory,
  MarketDataRow,
  Account,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api";

// ── Generic fetch wrapper ──
async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      body?.detail?.errors?.join("; ") ||
        body?.detail ||
        `API Error: ${res.status}`
    );
  }
  return res.json();
}

// ── Market Data ──
export const marketDataApi = {
  getAll: () => apiFetch<MarketData[]>("/market-data"),
  getSymbol: (symbol: string) =>
    apiFetch<MarketData>(`/market-data/${symbol}`),

  subscribeWs(onMessage: (data: MarketData[]) => void): WebSocket {
    const ws = new WebSocket(`${WS_BASE}/market-data/ws`);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch {
        // ignore parse errors
      }
    };
    return ws;
  },
};

// ── Instruments ──
export const instrumentsApi = {
  getAll: () => apiFetch<Instrument[]>("/instruments"),
  get: (symbol: string) => apiFetch<Instrument>(`/instruments/${symbol}`),
};

// ── Clients ──
export const clientsApi = {
  getAll: () => apiFetch<Client[]>("/clients"),
  get: (id: string) => apiFetch<Client>(`/clients/${id}`),
};

// ── Accounts ──
export const accountsApi = {
  getByClient: (clientId: string) =>
    apiFetch<Account[]>(`/accounts?client_id=${clientId}`),
  get: (id: string) => apiFetch<Account>(`/accounts/${id}`),
};

// ── Orders ──
export const ordersApi = {
  getAll: (params?: { status?: string; client_id?: string; symbol?: string }) => {
    const sp = new URLSearchParams();
    if (params?.status) sp.set("status", params.status);
    if (params?.client_id) sp.set("client_id", params.client_id);
    if (params?.symbol) sp.set("symbol", params.symbol);
    const qs = sp.toString();
    return apiFetch<Order[]>(`/orders${qs ? `?${qs}` : ""}`);
  },

  get: (orderId: string) => apiFetch<OrderDetail>(`/orders/${orderId}`),

  create: (data: CreateOrderRequest) =>
    apiFetch<Order>("/orders", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  cancel: (orderId: string, reason?: string) =>
    apiFetch<{ message: string; order_id: string }>(`/orders/${orderId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || "" }),
    }),

  amend: (
    orderId: string,
    data: { quantity?: number; limit_price?: number; stop_price?: number }
  ) =>
    apiFetch<Order>(`/orders/${orderId}/amend`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getExecutions: (orderId: string) =>
    apiFetch<import("./types").Execution[]>(`/orders/${orderId}/executions`),

  subscribeWs(
    onMessage: (data: { type: string; data: Record<string, unknown> }) => void
  ): WebSocket {
    const ws = new WebSocket(`${WS_BASE}/market-data/ws/orders`);
    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        onMessage(parsed);
      } catch {
        // ignore
      }
    };
    return ws;
  },
};

// ── Prefill ──
export const prefillApi = {
  getSuggestions: (data: PrefillRequest) =>
    apiFetch<PrefillResponse>("/prefill", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// ── Analytics ──
export const analyticsApi = {
  getInstruments: () => apiFetch<Instrument[]>("/analytics/instruments"),
  getClients: () => apiFetch<Client[]>("/analytics/clients"),
  getOrders: (page = 1, pageSize = 50) =>
    apiFetch<PaginatedResponse<Order>>(`/analytics/orders?page=${page}&page_size=${pageSize}`),
  getExecutions: (page = 1, pageSize = 50) =>
    apiFetch<PaginatedResponse<Execution>>(`/analytics/executions?page=${page}&page_size=${pageSize}`),
  getMarketData: (page = 1, pageSize = 100, symbol?: string) => {
    const sp = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (symbol) sp.set("symbol", symbol);
    return apiFetch<PaginatedResponse<MarketDataRow>>(`/analytics/market-data?${sp}`);
  },
  getOrderHistory: (page = 1, pageSize = 50) =>
    apiFetch<PaginatedResponse<OrderHistory>>(`/analytics/order-history?page=${page}&page_size=${pageSize}`),
  getCandlesticks: (symbol: string, interval = "1m") =>
    apiFetch<Candlestick[]>(`/analytics/candlesticks/${symbol}?interval=${interval}`),
  getSymbols: () => apiFetch<string[]>("/analytics/symbols"),
};
