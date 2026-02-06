"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "@/lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { DatabaseTable } from "@/components/database-table";
import { CandlestickChart } from "@/components/candlestick-chart";
import {
  Database,
  BarChart3,
  Users,
  FileText,
  Zap,
  TrendingUp,
  Clock,
  CandlestickChart as CandlestickIcon,
  RefreshCw,
  ArrowLeft,
} from "lucide-react";
import Link from "next/link";

export default function AnalyticsPage() {
  // Pagination states
  const [ordersPage, setOrdersPage] = useState(1);
  const [execPage, setExecPage] = useState(1);
  const [mdPage, setMdPage] = useState(1);
  const [histPage, setHistPage] = useState(1);
  const [mdSymbolFilter, setMdSymbolFilter] = useState<string | undefined>(
    undefined
  );

  // Candlestick state
  const [chartSymbol, setChartSymbol] = useState("RELIANCE");
  const [chartInterval, setChartInterval] = useState("1m");

  // ── Queries ──
  const instruments = useQuery({
    queryKey: ["analytics-instruments"],
    queryFn: analyticsApi.getInstruments,
  });

  const clients = useQuery({
    queryKey: ["analytics-clients"],
    queryFn: analyticsApi.getClients,
  });

  const orders = useQuery({
    queryKey: ["analytics-orders", ordersPage],
    queryFn: () => analyticsApi.getOrders(ordersPage),
  });

  const executions = useQuery({
    queryKey: ["analytics-executions", execPage],
    queryFn: () => analyticsApi.getExecutions(execPage),
  });

  const marketData = useQuery({
    queryKey: ["analytics-market-data", mdPage, mdSymbolFilter],
    queryFn: () => analyticsApi.getMarketData(mdPage, 100, mdSymbolFilter),
  });

  const orderHistory = useQuery({
    queryKey: ["analytics-order-history", histPage],
    queryFn: () => analyticsApi.getOrderHistory(histPage),
  });

  const symbols = useQuery({
    queryKey: ["analytics-symbols"],
    queryFn: analyticsApi.getSymbols,
  });

  const candlesticks = useQuery({
    queryKey: ["analytics-candlesticks", chartSymbol, chartInterval],
    queryFn: () => analyticsApi.getCandlesticks(chartSymbol, chartInterval),
    refetchInterval: 30_000, // auto-refresh every 30s
  });

  const tabBadge = (count?: number, loading?: boolean) => (
    <Badge
      variant="outline"
      className="ml-1.5 text-[10px] px-1.5 py-0 border-border/50 text-muted-foreground"
    >
      {loading ? "…" : count?.toLocaleString() ?? "0"}
    </Badge>
  );

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b border-border/50 bg-[oklch(0.12_0.06_255)] px-4 py-2 flex items-center justify-between shadow-lg shadow-black/20">
        <div className="flex items-center gap-3">
          <Link href="/">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div className="h-7 w-7 rounded bg-[oklch(0.68_0.15_240)] flex items-center justify-center">
            <Database className="h-4 w-4 text-white" />
          </div>
          <h1 className="text-lg font-bold tracking-tight text-white">
            Analytics
          </h1>
          <Badge
            variant="outline"
            className="text-xs border-[oklch(0.68_0.15_240)]/40 text-[oklch(0.68_0.15_240)]"
          >
            <Database className="h-3 w-3 mr-1" />
            SQLite
          </Badge>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 p-4">
        <Tabs defaultValue="candlestick" className="space-y-4">
          <TabsList className="bg-[oklch(0.12_0.06_255)] border border-border/50 flex-wrap h-auto py-1">
            <TabsTrigger value="candlestick" className="text-xs gap-1.5">
              <CandlestickIcon className="h-3.5 w-3.5" />
              Chart
            </TabsTrigger>
            <TabsTrigger value="instruments" className="text-xs gap-1.5">
              <BarChart3 className="h-3.5 w-3.5" />
              Instruments
              {tabBadge(instruments.data?.length, instruments.isLoading)}
            </TabsTrigger>
            <TabsTrigger value="clients" className="text-xs gap-1.5">
              <Users className="h-3.5 w-3.5" />
              Clients
              {tabBadge(clients.data?.length, clients.isLoading)}
            </TabsTrigger>
            <TabsTrigger value="orders" className="text-xs gap-1.5">
              <FileText className="h-3.5 w-3.5" />
              Orders
              {tabBadge(orders.data?.total, orders.isLoading)}
            </TabsTrigger>
            <TabsTrigger value="executions" className="text-xs gap-1.5">
              <Zap className="h-3.5 w-3.5" />
              Executions
              {tabBadge(executions.data?.total, executions.isLoading)}
            </TabsTrigger>
            <TabsTrigger value="market-data" className="text-xs gap-1.5">
              <TrendingUp className="h-3.5 w-3.5" />
              Market Data
              {tabBadge(marketData.data?.total, marketData.isLoading)}
            </TabsTrigger>
            <TabsTrigger value="history" className="text-xs gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              Order History
              {tabBadge(orderHistory.data?.total, orderHistory.isLoading)}
            </TabsTrigger>
          </TabsList>

          {/* ── Candlestick Chart ── */}
          <TabsContent value="candlestick" className="space-y-4">
            <div className="flex items-center gap-3 flex-wrap">
              <Select
                value={chartSymbol}
                onValueChange={(v) => setChartSymbol(v)}
              >
                <SelectTrigger className="w-48 h-8 bg-[oklch(0.12_0.06_255)] border-border/50 text-sm">
                  <SelectValue placeholder="Symbol" />
                </SelectTrigger>
                <SelectContent>
                  {(symbols.data || []).map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select
                value={chartInterval}
                onValueChange={(v) => setChartInterval(v)}
              >
                <SelectTrigger className="w-28 h-8 bg-[oklch(0.12_0.06_255)] border-border/50 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1m">1 min</SelectItem>
                  <SelectItem value="5m">5 min</SelectItem>
                  <SelectItem value="15m">15 min</SelectItem>
                </SelectContent>
              </Select>

              <Button
                variant="ghost"
                size="sm"
                className="h-8"
                onClick={() => candlesticks.refetch()}
                disabled={candlesticks.isFetching}
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 mr-1.5 ${
                    candlesticks.isFetching ? "animate-spin" : ""
                  }`}
                />
                Refresh
              </Button>

              {candlesticks.data && (
                <Badge
                  variant="outline"
                  className="text-xs text-muted-foreground"
                >
                  {candlesticks.data.length} candles · auto-refresh 30s
                </Badge>
              )}
            </div>

            {candlesticks.isLoading ? (
              <div className="h-[500px] rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground">
                Loading chart data…
              </div>
            ) : candlesticks.data && candlesticks.data.length > 0 ? (
              <CandlestickChart
                data={candlesticks.data}
                symbol={chartSymbol}
              />
            ) : (
              <div className="h-[500px] rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground">
                No market data yet. Snapshots are stored every 30 seconds — let
                the system run for a few minutes.
              </div>
            )}
          </TabsContent>

          {/* ── Instruments ── */}
          <TabsContent value="instruments">
            <DatabaseTable
              data={(instruments.data ?? []) as unknown as Record<string, unknown>[]}
            />
          </TabsContent>

          {/* ── Clients ── */}
          <TabsContent value="clients">
            <DatabaseTable
              data={(clients.data ?? []) as unknown as Record<string, unknown>[]}
            />
          </TabsContent>

          {/* ── Orders (paginated) ── */}
          <TabsContent value="orders">
            <DatabaseTable
              data={(orders.data?.data ?? []) as unknown as Record<string, unknown>[]}
              totalRows={orders.data?.total}
              page={ordersPage}
              totalPages={orders.data?.total_pages}
              onPageChange={setOrdersPage}
              pageSize={50}
            />
          </TabsContent>

          {/* ── Executions (paginated) ── */}
          <TabsContent value="executions">
            <DatabaseTable
              data={(executions.data?.data ?? []) as unknown as Record<string, unknown>[]}
              totalRows={executions.data?.total}
              page={execPage}
              totalPages={executions.data?.total_pages}
              onPageChange={setExecPage}
              pageSize={50}
            />
          </TabsContent>

          {/* ── Market Data (paginated + filter) ── */}
          <TabsContent value="market-data" className="space-y-3">
            <div className="flex items-center gap-3">
              <Select
                value={mdSymbolFilter ?? "ALL"}
                onValueChange={(v) => {
                  setMdSymbolFilter(v === "ALL" ? undefined : v);
                  setMdPage(1);
                }}
              >
                <SelectTrigger className="w-48 h-8 bg-[oklch(0.12_0.06_255)] border-border/50 text-sm">
                  <SelectValue placeholder="All symbols" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Symbols</SelectItem>
                  {(symbols.data || []).map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DatabaseTable
              data={(marketData.data?.data ?? []) as unknown as Record<string, unknown>[]}
              totalRows={marketData.data?.total}
              page={mdPage}
              totalPages={marketData.data?.total_pages}
              onPageChange={setMdPage}
              pageSize={100}
            />
          </TabsContent>

          {/* ── Order History (paginated) ── */}
          <TabsContent value="history">
            <DatabaseTable
              data={(orderHistory.data?.data ?? []) as unknown as Record<string, unknown>[]}
              totalRows={orderHistory.data?.total}
              page={histPage}
              totalPages={orderHistory.data?.total_pages}
              onPageChange={setHistPage}
              pageSize={50}
            />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
