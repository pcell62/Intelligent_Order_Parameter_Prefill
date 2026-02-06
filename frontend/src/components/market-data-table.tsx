"use client";

import { useMemo } from "react";
import type { MarketData } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowUpRight, ArrowDownRight, Clock, ShoppingCart } from "lucide-react";

interface MarketDataTableProps {
  data: MarketData[];
  onQuickOrder: (symbol: string) => void;
}

function formatCurrency(val: number) {
  return `₹${val.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatNumber(val: number) {
  if (val >= 10000000) return `${(val / 10000000).toFixed(2)}Cr`;
  if (val >= 100000) return `${(val / 100000).toFixed(2)}L`;
  if (val >= 1000) return `${(val / 1000).toFixed(1)}K`;
  return val.toLocaleString();
}

export function MarketDataTable({ data, onQuickOrder }: MarketDataTableProps) {
  const timeToClose = data[0]?.time_to_close ?? 0;

  const sortedData = useMemo(
    () => [...data].sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [data]
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">
            Live Market Data
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant={timeToClose <= 30 ? "destructive" : "secondary"}
              className="font-mono"
            >
              <Clock className="h-3 w-3 mr-1" />
              {timeToClose > 0 ? `${timeToClose}m to close` : "Market Closed"}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[120px]">Symbol</TableHead>
                <TableHead className="text-right">Bid</TableHead>
                <TableHead className="text-right">Ask</TableHead>
                <TableHead className="text-right">LTP</TableHead>
                <TableHead className="text-right">Chg %</TableHead>
                <TableHead className="text-right">Spread (bps)</TableHead>
                <TableHead className="text-right">Vol %</TableHead>
                <TableHead className="text-right">Day Vol</TableHead>
                <TableHead className="text-right">Avg Size</TableHead>
                <TableHead className="text-right">High</TableHead>
                <TableHead className="text-right">Low</TableHead>
                <TableHead className="w-[80px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedData.map((row) => {
                const isUp = row.change_pct >= 0;
                return (
                  <TableRow key={row.symbol} className="hover:bg-muted/50 cursor-pointer group">
                    <TableCell className="font-semibold">{row.symbol}</TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatCurrency(row.bid)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatCurrency(row.ask)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm font-semibold">
                      {formatCurrency(row.ltp)}
                    </TableCell>
                    <TableCell className="text-right">
                      <span
                        className={`inline-flex items-center font-mono text-sm font-medium ${
                          isUp ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {isUp ? (
                          <ArrowUpRight className="h-3 w-3 mr-0.5" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3 mr-0.5" />
                        )}
                        {Math.abs(row.change_pct).toFixed(2)}%
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {row.spread_bps.toFixed(1)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {row.volatility.toFixed(2)}%
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatNumber(row.day_volume)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatNumber(row.avg_trade_size)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm text-emerald-400">
                      {formatCurrency(row.high)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm text-rose-400">
                      {formatCurrency(row.low)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => onQuickOrder(row.symbol)}
                      >
                        <ShoppingCart className="h-3.5 w-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {sortedData.length === 0 && (
                <TableRow>
                  <TableCell colSpan={12} className="text-center py-8 text-muted-foreground">
                    Connecting to market data feed...
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
