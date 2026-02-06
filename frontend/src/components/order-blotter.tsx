"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ordersApi } from "@/lib/api";
import type { Order, OrderDetail } from "@/lib/types";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { X, Eye, Ban, ListFilter } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  VALIDATED: "bg-sky-500/20 text-sky-400 border-sky-500/30",
  WORKING: "bg-sky-500/20 text-sky-400 border-sky-500/30",
  PARTIALLY_FILLED: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  FILLED: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  CANCELLED: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  REJECTED: "bg-red-500/20 text-red-400 border-red-500/30",
  EXPIRED: "bg-slate-500/20 text-slate-400 border-slate-500/30",
};

function formatTime(ts: string) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

export function OrderBlotter() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [selectedOrder, setSelectedOrder] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["orders", statusFilter],
    queryFn: () =>
      ordersApi.getAll(statusFilter !== "ALL" ? { status: statusFilter } : {}),
    refetchInterval: 3000,
  });

  const { data: orderDetail } = useQuery({
    queryKey: ["order-detail", selectedOrder],
    queryFn: () => ordersApi.get(selectedOrder!),
    enabled: !!selectedOrder,
  });

  // WebSocket for real-time order updates
  useEffect(() => {
    const ws = ordersApi.subscribeWs(() => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      if (selectedOrder) {
        queryClient.invalidateQueries({ queryKey: ["order-detail", selectedOrder] });
      }
    });
    wsRef.current = ws;
    return () => ws.close();
  }, [queryClient, selectedOrder]);

  const handleCancel = async (orderId: string) => {
    try {
      await ordersApi.cancel(orderId, "Cancelled by trader");
      toast.success(`Order ${orderId} cancelled`);
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel");
    }
  };

  const handleViewDetail = (orderId: string) => {
    setSelectedOrder(orderId);
    setDetailOpen(true);
  };

  const activeCount = orders.filter(
    (o) => o.status === "WORKING" || o.status === "PARTIALLY_FILLED"
  ).length;

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <CardTitle className="text-base font-semibold">
                Order Blotter
              </CardTitle>
              {activeCount > 0 && (
                <Badge variant="secondary" className="font-mono">
                  {activeCount} active
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              <ListFilter className="h-4 w-4 text-muted-foreground" />
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-[160px] h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Orders</SelectItem>
                  <SelectItem value="WORKING">Working</SelectItem>
                  <SelectItem value="PARTIALLY_FILLED">Partially Filled</SelectItem>
                  <SelectItem value="FILLED">Filled</SelectItem>
                  <SelectItem value="CANCELLED">Cancelled</SelectItem>
                  <SelectItem value="REJECTED">Rejected</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[100px]">Order ID</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Algo</TableHead>
                  <TableHead>TIF</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Filled</TableHead>
                  <TableHead className="text-right">Avg Price</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead className="w-[100px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.map((order) => {
                  const fillPct =
                    order.quantity > 0
                      ? Math.round((order.filled_quantity / order.quantity) * 100)
                      : 0;
                  const canCancel = !["FILLED", "CANCELLED", "REJECTED", "EXPIRED"].includes(
                    order.status
                  );

                  return (
                    <TableRow key={order.order_id} className="hover:bg-muted/50">
                      <TableCell className="font-mono text-xs">
                        {order.order_id}
                      </TableCell>
                      <TableCell className="text-xs">
                        {formatTime(order.created_at)}
                      </TableCell>
                      <TableCell className="text-xs">{order.client_id}</TableCell>
                      <TableCell className="font-semibold text-sm">
                        {order.symbol}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            order.direction === "BUY"
                              ? "text-emerald-400 border-emerald-500/30"
                              : "text-rose-400 border-rose-500/30"
                          }
                        >
                          {order.direction}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">{order.order_type}</TableCell>
                      <TableCell className="text-xs">
                        {order.algo_type !== "NONE" ? order.algo_type : "—"}
                      </TableCell>
                      <TableCell className="text-xs font-mono">
                        {order.tif || "GFD"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {order.quantity.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {order.filled_quantity.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {order.avg_fill_price > 0
                          ? `₹${order.avg_fill_price.toFixed(2)}`
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={STATUS_COLORS[order.status] || ""}
                        >
                          {order.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="w-16 bg-muted rounded-full h-1.5">
                            <div
                              className="bg-primary h-1.5 rounded-full transition-all"
                              style={{ width: `${fillPct}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono text-muted-foreground">
                            {fillPct}%
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() => handleViewDetail(order.order_id)}
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                          {canCancel && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-rose-400 hover:text-rose-300"
                              onClick={() => handleCancel(order.order_id)}
                            >
                              <Ban className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!isLoading && orders.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={14}
                      className="text-center py-8 text-muted-foreground min-w-0"
                    >
                      No orders found. Click &quot;New Order&quot; to create one.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Order Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="font-mono">
              Order: {orderDetail?.order?.order_id}
            </DialogTitle>
          </DialogHeader>
          {orderDetail && <OrderDetailView detail={orderDetail} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function OrderDetailView({ detail }: { detail: OrderDetail }) {
  const { order, executions, history } = detail;
  const algoParams = (() => {
    try {
      return JSON.parse(order.algo_params || "{}");
    } catch {
      return {};
    }
  })();

  return (
    <ScrollArea className="max-h-[60vh]">
      <div className="space-y-4 pr-4">
        {/* Order Summary */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-muted-foreground">Symbol</span>
            <p className="font-semibold">{order.symbol}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Client</span>
            <p className="font-semibold">{order.client_id}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Direction</span>
            <p>
              <Badge
                variant="outline"
                className={
                  order.direction === "BUY"
                    ? "text-emerald-400 border-emerald-500/30"
                    : "text-rose-400 border-rose-500/30"
                }
              >
                {order.direction}
              </Badge>
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Status</span>
            <p>
              <Badge variant="outline" className={STATUS_COLORS[order.status]}>
                {order.status}
              </Badge>
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Quantity</span>
            <p className="font-mono">{order.quantity.toLocaleString()}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Filled</span>
            <p className="font-mono">
              {order.filled_quantity.toLocaleString()} (
              {Math.round((order.filled_quantity / order.quantity) * 100)}%)
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Avg Fill Price</span>
            <p className="font-mono">
              {order.avg_fill_price > 0
                ? `₹${order.avg_fill_price.toFixed(2)}`
                : "—"}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Order Type</span>
            <p>
              {order.order_type}
              {order.limit_price ? ` @ ₹${order.limit_price.toFixed(2)}` : ""}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">TIF</span>
            <p className="font-semibold">{order.tif || "GFD"}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Urgency</span>
            <p className="font-mono">{order.urgency ?? 50}/100</p>
          </div>
          <div>
            <span className="text-muted-foreground">Capacity</span>
            <p>{order.capacity || "AGENCY"}</p>
          </div>
          {order.get_done === 1 && (
            <div>
              <span className="text-muted-foreground">Get Done</span>
              <p className="text-amber-400 font-medium">Yes</p>
            </div>
          )}
          {order.algo_type !== "NONE" && (
            <>
              <div>
                <span className="text-muted-foreground">Algo</span>
                <p className="font-semibold">{order.algo_type}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Time Window</span>
                <p className="font-mono">
                  {order.start_time || "—"} → {order.end_time || "—"}
                </p>
              </div>
            </>
          )}
          {Object.keys(algoParams).length > 0 && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Algo Parameters</span>
              <div className="flex flex-wrap gap-2 mt-1">
                {Object.entries(algoParams).map(([k, v]) =>
                  v != null ? (
                    <Badge key={k} variant="secondary" className="text-xs">
                      {k.replace(/_/g, " ")}: {String(v)}
                    </Badge>
                  ) : null
                )}
              </div>
            </div>
          )}
          {order.order_notes && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Notes</span>
              <p className="text-sm italic">{order.order_notes}</p>
            </div>
          )}
        </div>

        <Separator />

        {/* Executions */}
        <div>
          <h4 className="text-sm font-semibold mb-2">
            Executions ({executions.length})
          </h4>
          {executions.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead>Venue</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {executions.slice(0, 20).map((exec) => (
                  <TableRow key={exec.execution_id}>
                    <TableCell className="text-xs">
                      {formatTime(exec.executed_at)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {exec.fill_quantity.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      ₹{exec.fill_price.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-xs">{exec.venue}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">No executions yet</p>
          )}
        </div>

        <Separator />

        {/* Audit Trail */}
        <div>
          <h4 className="text-sm font-semibold mb-2">
            Audit Trail ({history.length})
          </h4>
          <div className="space-y-1">
            {history.map((h) => (
              <div key={h.id} className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground w-20">
                  {formatTime(h.created_at)}
                </span>
                <Badge variant="outline" className="text-xs">
                  {h.action}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}
