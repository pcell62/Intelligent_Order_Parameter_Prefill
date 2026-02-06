"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketDataApi, clientsApi, instrumentsApi } from "@/lib/api";
import type { MarketData } from "@/lib/types";
import { Navbar } from "@/components/navbar";
import { MarketDataTable } from "@/components/market-data-table";
import { OrderBlotter } from "@/components/order-blotter";
import { OrderTicket } from "@/components/order-ticket";

export default function Home() {
  const [liveMarketData, setLiveMarketData] = useState<MarketData[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [orderTicketOpen, setOrderTicketOpen] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: initialMarketData } = useQuery({
    queryKey: ["market-data"],
    queryFn: marketDataApi.getAll,
  });

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: clientsApi.getAll,
  });

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: instrumentsApi.getAll,
  });

  useEffect(() => {
    const ws = marketDataApi.subscribeWs((data) => {
      setLiveMarketData(data);
    });
    wsRef.current = ws;
    return () => {
      ws.close();
    };
  }, []);

  const marketData =
    liveMarketData.length > 0 ? liveMarketData : initialMarketData || [];

  const handleQuickOrder = useCallback((symbol: string) => {
    setSelectedSymbol(symbol);
    setOrderTicketOpen(true);
  }, []);

  const handleNewOrder = useCallback(() => {
    setSelectedSymbol(null);
    setOrderTicketOpen(true);
  }, []);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Navbar onNewOrder={handleNewOrder} />

      <main className="flex-1 p-4 space-y-4">
        <MarketDataTable data={marketData} onQuickOrder={handleQuickOrder} />
        <OrderBlotter />
      </main>

      <OrderTicket
        open={orderTicketOpen}
        onOpenChange={setOrderTicketOpen}
        prefilledSymbol={selectedSymbol}
        clients={clients || []}
        instruments={instruments || []}
        marketData={marketData}
      />
    </div>
  );
}
