"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ShieldCheck, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";

interface ConfirmationData {
  client_name: string;
  account_name: string | null;
  symbol: string;
  direction: string;
  order_type: string;
  quantity: number;
  limit_price?: number | null;
  algo_type: string;
  aggression?: string;
  tif: string;
  urgency: number;
  get_done: boolean;
  capacity: string;
  estimated_value: number | null;
}

interface OrderConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  data: ConfirmationData;
  onConfirm: () => void;
  isSubmitting: boolean;
}

export function OrderConfirmationDialog({
  open,
  onOpenChange,
  data,
  onConfirm,
  isSubmitting,
}: OrderConfirmationDialogProps) {
  const isBuy = data.direction === "BUY";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px] bg-[oklch(0.16_0.05_255)] border-[oklch(0.25_0.05_255)]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg">
            <ShieldCheck className="h-5 w-5 text-[oklch(0.68_0.15_240)]" />
            Confirm Trade Execution
          </DialogTitle>
          <DialogDescription>
            Review the order details before submitting to the execution engine.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-[oklch(0.25_0.05_255)] bg-[oklch(0.14_0.06_255)] p-4 space-y-3">
          {/* Direction + Symbol headline */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {isBuy ? (
                <TrendingUp className="h-5 w-5 text-emerald-400" />
              ) : (
                <TrendingDown className="h-5 w-5 text-rose-400" />
              )}
              <span className="text-xl font-bold">{data.symbol}</span>
            </div>
            <Badge
              variant="outline"
              className={
                isBuy
                  ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                  : "border-rose-500/50 bg-rose-500/10 text-rose-400"
              }
            >
              {data.direction}
            </Badge>
          </div>

          <Separator className="bg-[oklch(0.25_0.05_255)]" />

          {/* Detail rows */}
          <div className="grid grid-cols-2 gap-y-2.5 text-sm">
            <span className="text-muted-foreground">Client</span>
            <span className="text-right font-medium">{data.client_name}</span>

            {data.account_name && (
              <>
                <span className="text-muted-foreground">Account</span>
                <span className="text-right font-medium">{data.account_name}</span>
              </>
            )}

            <span className="text-muted-foreground">Order Type</span>
            <span className="text-right font-medium">{data.order_type}</span>

            <span className="text-muted-foreground">Quantity</span>
            <span className="text-right font-mono font-medium">
              {data.quantity.toLocaleString()}
            </span>

            {data.limit_price != null && (
              <>
                <span className="text-muted-foreground">Limit Price</span>
                <span className="text-right font-mono font-medium">
                  ₹{data.limit_price.toLocaleString()}
                </span>
              </>
            )}

            <span className="text-muted-foreground">Algorithm</span>
            <span className="text-right font-medium">
              {data.algo_type === "NONE" ? "Direct" : data.algo_type}
            </span>

            {data.aggression && (
              <>
                <span className="text-muted-foreground">Aggression</span>
                <span className="text-right font-medium">{data.aggression}</span>
              </>
            )}

            <span className="text-muted-foreground">TIF</span>
            <span className="text-right font-medium">{data.tif}</span>

            <span className="text-muted-foreground">Urgency</span>
            <span className="text-right font-mono font-medium">{data.urgency}/100</span>

            <span className="text-muted-foreground">Capacity</span>
            <span className="text-right font-medium">{data.capacity}</span>

            {data.get_done && (
              <>
                <span className="text-muted-foreground">Get Done</span>
                <span className="text-right font-medium text-amber-400">Yes — Must Complete</span>
              </>
            )}

            {data.estimated_value != null && (
              <>
                <Separator className="col-span-2 bg-[oklch(0.25_0.05_255)]" />
                <span className="text-muted-foreground font-medium">Est. Value</span>
                <span className="text-right font-mono font-bold text-[oklch(0.68_0.15_240)]">
                  ₹{data.estimated_value.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Warning note */}
        <div className="flex items-start gap-2 text-xs text-amber-400/80 bg-amber-500/5 border border-amber-500/20 rounded-md p-2.5">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            This order will be routed to the execution engine immediately upon confirmation.
            Ensure all parameters are correct.
          </span>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
            className="border-[oklch(0.25_0.05_255)] hover:bg-[oklch(0.20_0.04_255)]"
          >
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isSubmitting}
            className={
              isBuy
                ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                : "bg-rose-600 hover:bg-rose-700 text-white"
            }
          >
            {isSubmitting ? "Executing..." : "Execute Trade"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
