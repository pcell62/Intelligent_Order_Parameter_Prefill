"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ordersApi, prefillApi } from "@/lib/api";
import type {
  Client,
  Instrument,
  MarketData,
  Direction,
  OrderType,
  AlgoType,
  TIF,
  Capacity,
  CreateOrderRequest,
  PrefillResponse,
  Account,
} from "@/lib/types";
import { accountsApi } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  TooltipProvider,
} from "@/components/ui/tooltip";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { OrderConfirmationDialog } from "@/components/order-confirmation-dialog";
import { toast } from "sonner";
import {
  Send, AlertTriangle, Info, Sparkles, Lightbulb, Loader2,
  Zap, ZapOff, Gauge, ChevronLeft, ChevronRight, Target,
  XCircle,
} from "lucide-react";

interface OrderTicketProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  prefilledSymbol: string | null;
  clients: Client[];
  instruments: Instrument[];
  marketData: MarketData[];
}

const DEFAULT_FORM = {
  client_id: "",
  account_id: "",
  symbol: "",
  direction: "BUY" as Direction,
  order_type: "MARKET" as OrderType,
  quantity: "",
  limit_price: "",
  stop_price: "",
  algo_type: "NONE" as AlgoType,
  start_time: "",
  end_time: "",
  tif: "GFD" as TIF,
  urgency: 50,
  get_done: false,
  capacity: "AGENCY" as Capacity,
  order_notes: "",
  // Algo params
  target_participation_rate: "10",
  min_order_size: "100",
  max_order_size: "50000",
  volume_curve: "Historical",
  max_volume_pct: "20",
  display_quantity: "5000",
  aggression_level: "Medium",
};

// Urgency zone labels & colors
function urgencyZone(u: number): { label: string; color: string; bg: string } {
  if (u <= 20) return { label: "Patient", color: "text-emerald-400", bg: "bg-emerald-500" };
  if (u <= 40) return { label: "Moderate", color: "text-sky-400", bg: "bg-sky-500" };
  if (u <= 60) return { label: "Balanced", color: "text-violet-400", bg: "bg-violet-500" };
  if (u <= 80) return { label: "Active", color: "text-amber-400", bg: "bg-amber-500" };
  return { label: "Urgent", color: "text-rose-400", bg: "bg-rose-500" };
}

export function OrderTicket({
  open,
  onOpenChange,
  prefilledSymbol,
  clients,
  instruments,
  marketData,
}: OrderTicketProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(DEFAULT_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [prefill, setPrefill] = useState<PrefillResponse | null>(null);
  const [prefilling, setPrefilling] = useState(false);
  const [prefilledFields, setPrefilledFields] = useState<Set<string>>(new Set());
  const [prefillEnabled, setPrefillEnabled] = useState(true);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [riskAversion, setRiskAversion] = useState<number>(50);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [showWhyNot, setShowWhyNot] = useState(false);
  const urgencyDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const notesDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track manual overrides so re-prefill doesn't clobber trader's choices
  const overriddenFieldsRef = useRef<Set<string>>(new Set());
  const urgencyManualRef = useRef<number | null>(null);

  // Set prefilled symbol when dialog opens
  useEffect(() => {
    if (open) {
      setForm((f) => ({
        ...DEFAULT_FORM,
        symbol: prefilledSymbol || f.symbol,
      }));
      setErrors([]);
      setPrefill(null);
      setPrefilledFields(new Set());
      overriddenFieldsRef.current = new Set();
      urgencyManualRef.current = null;
      setAccounts([]);
      setRiskAversion(50);
      setShowConfirmation(false);
      setShowWhyNot(false);
    }
  }, [open, prefilledSymbol]);

  // Fetch accounts when client changes
  useEffect(() => {
    if (!form.client_id) {
      setAccounts([]);
      setForm((f) => ({ ...f, account_id: "" }));
      return;
    }
    const client = clients.find((c) => c.client_id === form.client_id);
    if (client) setRiskAversion(client.risk_aversion ?? 50);

    accountsApi.getByClient(form.client_id).then((accts) => {
      setAccounts(accts);
      const def = accts.find((a) => a.is_default);
      if (def) setForm((f) => ({ ...f, account_id: def.account_id }));
      else if (accts.length === 1) setForm((f) => ({ ...f, account_id: accts[0].account_id }));
      else setForm((f) => ({ ...f, account_id: "" }));
    }).catch(() => setAccounts([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.client_id, clients]);

  // ── Prefill trigger ──
  const triggerPrefill = useCallback(
    async (clientId: string, symbol: string, direction: string, urgencyVal?: number, orderNotes?: string, qty?: number, riskAv?: number) => {
      if (!clientId || !symbol) return;
      setPrefilling(true);
      try {
        const result = await prefillApi.getSuggestions({
          client_id: clientId,
          symbol,
          direction,
          urgency: urgencyVal,
          quantity: qty || undefined,
          risk_aversion: riskAv,
          order_notes: orderNotes || undefined,
        });
        setPrefill(result);

        // Apply suggestions to form — skip fields the trader has manually overridden
        const filled = new Set<string>();
        const ov = overriddenFieldsRef.current;
        setForm((prev) => {
          const next = { ...prev };
          const s = result.suggestions;

          if (s.algo_type && !ov.has("algo_type")) { next.algo_type = s.algo_type as AlgoType; filled.add("algo_type"); }
          if (s.order_type && !ov.has("order_type")) { next.order_type = s.order_type as OrderType; filled.add("order_type"); }
          if (s.limit_price && !ov.has("limit_price")) { next.limit_price = String(s.limit_price); filled.add("limit_price"); }
          if (s.start_time && !ov.has("start_time")) { next.start_time = String(s.start_time); filled.add("start_time"); }
          if (s.end_time && !ov.has("end_time")) { next.end_time = String(s.end_time); filled.add("end_time"); }
          if (s.aggression_level && !ov.has("aggression_level")) { next.aggression_level = String(s.aggression_level); filled.add("aggression_level"); }
          if (s.target_participation_rate && !ov.has("target_participation_rate")) { next.target_participation_rate = String(s.target_participation_rate); filled.add("target_participation_rate"); }
          if (s.min_order_size && !ov.has("min_order_size")) { next.min_order_size = String(s.min_order_size); filled.add("min_order_size"); }
          if (s.max_order_size && !ov.has("max_order_size")) { next.max_order_size = String(s.max_order_size); filled.add("max_order_size"); }
          if (s.volume_curve && !ov.has("volume_curve")) { next.volume_curve = String(s.volume_curve); filled.add("volume_curve"); }
          if (s.max_volume_pct && !ov.has("max_volume_pct")) { next.max_volume_pct = String(s.max_volume_pct); filled.add("max_volume_pct"); }
          if (s.display_quantity && !ov.has("display_quantity")) { next.display_quantity = String(s.display_quantity); filled.add("display_quantity"); }
          if (s.quantity && !prev.quantity) { next.quantity = String(s.quantity); filled.add("quantity"); }
          if (s.order_notes && !prev.order_notes) { next.order_notes = String(s.order_notes); filled.add("order_notes"); }
          if (s.tif && !ov.has("tif")) { next.tif = String(s.tif) as TIF; filled.add("tif"); }
          if (s.get_done !== undefined && !ov.has("get_done")) { next.get_done = !!s.get_done; filled.add("get_done"); }

          // Set urgency from response (only if trader hasn't manually overridden it)
          if (urgencyManualRef.current === null) {
            next.urgency = result.urgency_score;
          }

          return next;
        });
        setPrefilledFields(filled);

        const count = Object.keys(result.suggestions).length;
        toast.info(`Smart Prefill: ${count} fields suggested`, {
          description: "Fields highlighted with ✨ were auto-filled. Hover for explanations.",
          duration: 4000,
        });
      } catch {
        // Prefill is optional — silently fail
      } finally {
        setPrefilling(false);
      }
    },
    []
  );

  // Fire prefill when client or symbol changes (reset overrides — new context)
  useEffect(() => {
    if (prefillEnabled && form.client_id && form.symbol) {
      overriddenFieldsRef.current = new Set();
      urgencyManualRef.current = null;
      const qty = parseInt(form.quantity) || undefined;
      triggerPrefill(form.client_id, form.symbol, form.direction, undefined, form.order_notes, qty, riskAversion);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.client_id, form.symbol, prefillEnabled, triggerPrefill]);

  // Re-fire prefill when direction changes
  useEffect(() => {
    if (prefillEnabled && form.client_id && form.symbol && prefill) {
      const qty = parseInt(form.quantity) || undefined;
      triggerPrefill(form.client_id, form.symbol, form.direction, urgencyManualRef.current ?? undefined, form.order_notes, qty, riskAversion);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.direction]);

  // Re-fire prefill when order notes change (debounced — user may still be typing)
  useEffect(() => {
    if (!prefillEnabled || !form.client_id || !form.symbol) return;
    if (notesDebounce.current) clearTimeout(notesDebounce.current);
    notesDebounce.current = setTimeout(() => {
      const qty = parseInt(form.quantity) || undefined;
      triggerPrefill(form.client_id, form.symbol, form.direction, urgencyManualRef.current ?? undefined, form.order_notes, qty, riskAversion);
    }, 800);
    return () => { if (notesDebounce.current) clearTimeout(notesDebounce.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.order_notes]);

  // Re-fire prefill when quantity changes (debounced — user may still be typing)
  const qtyDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!prefillEnabled || !form.client_id || !form.symbol) return;
    const qty = parseInt(form.quantity) || 0;
    if (!qty) return;
    if (qtyDebounce.current) clearTimeout(qtyDebounce.current);
    qtyDebounce.current = setTimeout(() => {
      triggerPrefill(form.client_id, form.symbol, form.direction, urgencyManualRef.current ?? undefined, form.order_notes, qty, riskAversion);
    }, 600);
    return () => { if (qtyDebounce.current) clearTimeout(qtyDebounce.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.quantity]);

  // Re-fire prefill when risk aversion slider changes (debounced)
  const riskDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!prefillEnabled || !form.client_id || !form.symbol || !prefill) return;
    if (riskDebounce.current) clearTimeout(riskDebounce.current);
    riskDebounce.current = setTimeout(() => {
      const qty = parseInt(form.quantity) || undefined;
      triggerPrefill(form.client_id, form.symbol, form.direction, urgencyManualRef.current ?? undefined, form.order_notes, qty, riskAversion);
    }, 400);
    return () => { if (riskDebounce.current) clearTimeout(riskDebounce.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskAversion]);

  // ── Urgency slider change → debounced re-prefill ──
  const handleUrgencyChange = useCallback(
    (val: number[]) => {
      const u = val[0];
      setForm((f) => ({ ...f, urgency: u }));
      urgencyManualRef.current = u;   // remember trader override

      // Debounce API call
      if (urgencyDebounce.current) clearTimeout(urgencyDebounce.current);
      urgencyDebounce.current = setTimeout(() => {
        if (prefillEnabled && form.client_id && form.symbol) {
          const qty = parseInt(form.quantity) || undefined;
          triggerPrefill(form.client_id, form.symbol, form.direction, u, form.order_notes, qty, riskAversion);
        }
      }, 400);
    },
    [prefillEnabled, form.client_id, form.symbol, form.direction, form.order_notes, riskAversion, triggerPrefill]
  );

  // Quick-adjust buttons
  const nudgeUrgency = useCallback(
    (delta: number) => {
      const newVal = Math.max(0, Math.min(100, form.urgency + delta));
      handleUrgencyChange([newVal]);
    },
    [form.urgency, handleUrgencyChange]
  );

  // Handle toggle: clear prefill state when disabled
  const handlePrefillToggle = useCallback(
    (enabled: boolean) => {
      setPrefillEnabled(enabled);
      if (!enabled) {
        setPrefill(null);
        setPrefilledFields(new Set());
        overriddenFieldsRef.current = new Set();
        urgencyManualRef.current = null;
        setForm((prev) => {
          const next = { ...prev };
          if (prefilledFields.has("algo_type")) next.algo_type = DEFAULT_FORM.algo_type;
          if (prefilledFields.has("order_type")) next.order_type = DEFAULT_FORM.order_type;
          if (prefilledFields.has("limit_price")) next.limit_price = DEFAULT_FORM.limit_price;
          if (prefilledFields.has("start_time")) next.start_time = DEFAULT_FORM.start_time;
          if (prefilledFields.has("end_time")) next.end_time = DEFAULT_FORM.end_time;
          if (prefilledFields.has("aggression_level")) next.aggression_level = DEFAULT_FORM.aggression_level;
          if (prefilledFields.has("target_participation_rate")) next.target_participation_rate = DEFAULT_FORM.target_participation_rate;
          if (prefilledFields.has("min_order_size")) next.min_order_size = DEFAULT_FORM.min_order_size;
          if (prefilledFields.has("max_order_size")) next.max_order_size = DEFAULT_FORM.max_order_size;
          if (prefilledFields.has("volume_curve")) next.volume_curve = DEFAULT_FORM.volume_curve;
          if (prefilledFields.has("max_volume_pct")) next.max_volume_pct = DEFAULT_FORM.max_volume_pct;
          if (prefilledFields.has("display_quantity")) next.display_quantity = DEFAULT_FORM.display_quantity;
          if (prefilledFields.has("quantity")) next.quantity = DEFAULT_FORM.quantity;
          if (prefilledFields.has("order_notes")) next.order_notes = DEFAULT_FORM.order_notes;
          if (prefilledFields.has("tif")) next.tif = DEFAULT_FORM.tif;
          if (prefilledFields.has("get_done")) next.get_done = DEFAULT_FORM.get_done;
          next.urgency = 50;
          return next;
        });
        toast.info("Smart Prefill disabled", { description: "Fields reset to defaults.", duration: 2000 });
      } else {
        if (form.client_id && form.symbol) {
          const qty = parseInt(form.quantity) || undefined;
          triggerPrefill(form.client_id, form.symbol, form.direction, undefined, form.order_notes, qty, riskAversion);
        }
      }
    },
    [prefilledFields, form.client_id, form.symbol, form.direction, form.order_notes, riskAversion, triggerPrefill]
  );

  const update = (field: string, value: string | boolean) => {
    setForm((f) => ({ ...f, [field]: value }));
    setErrors([]);
    // Remove confidence badge and track override so re-prefill respects trader's choice
    if (prefilledFields.has(field)) {
      overriddenFieldsRef.current.add(field);
      setPrefilledFields((prev) => {
        const next = new Set(prev);
        next.delete(field);
        return next;
      });
    }
  };

  const symbolMd = useMemo(
    () => marketData.find((m) => m.symbol === form.symbol),
    [marketData, form.symbol]
  );

  const selectedClient = useMemo(
    () => clients.find((c) => c.client_id === form.client_id),
    [clients, form.client_id]
  );

  const selectedInstrument = useMemo(
    () => instruments.find((i) => i.symbol === form.symbol),
    [instruments, form.symbol]
  );

  const notional = useMemo(() => {
    const qty = parseInt(form.quantity) || 0;
    return qty * (symbolMd?.ltp || 0);
  }, [form.quantity, symbolMd]);

  const advPct = useMemo(() => {
    const qty = parseInt(form.quantity) || 0;
    const adv = selectedInstrument?.adv || 0;
    if (!qty || !adv) return null;
    return (qty / adv) * 100;
  }, [form.quantity, selectedInstrument]);

  // Inline explanation badge
  const PrefillHint = ({ field }: { field: string }) => {
    if (!prefilledFields.has(field) || !prefill?.explanations[field]) return null;
    const conf = prefill.confidence[field] ?? 0;
    const pct = Math.round(conf * 100);
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex items-center gap-1 ml-1.5 cursor-help">
              <Sparkles className="h-3.5 w-3.5 text-[oklch(0.68_0.15_240)]" />
              <span className="text-[10px] font-medium text-[oklch(0.68_0.15_240)]">{pct}%</span>
            </span>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs text-xs">
            <div className="flex items-start gap-1.5">
              <Lightbulb className="h-3.5 w-3.5 mt-0.5 shrink-0 text-amber-400" />
              <span>{prefill.explanations[field]}</span>
            </div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  };

  const selectedAccount = useMemo(
    () => accounts.find((a) => a.account_id === form.account_id),
    [accounts, form.account_id]
  );

  const riskLabel = useMemo(() => {
    if (riskAversion >= 70) return "Conservative";
    if (riskAversion <= 29) return "Aggressive";
    return "Moderate";
  }, [riskAversion]);

  const uZone = useMemo(() => urgencyZone(form.urgency), [form.urgency]);

  const handleSubmit = () => {
    setErrors([]);
    const qty = parseInt(form.quantity);
    if (!qty || qty <= 0) {
      setErrors(["Quantity must be a positive number"]);
      return;
    }
    setShowConfirmation(true);
  };

  const executeOrder = async () => {
    setSubmitting(true);
    setErrors([]);
    try {
      const qty = parseInt(form.quantity);
      const payload: CreateOrderRequest = {
        client_id: form.client_id,
        symbol: form.symbol,
        direction: form.direction,
        order_type: form.order_type,
        quantity: qty,
        limit_price: form.order_type === "LIMIT" ? parseFloat(form.limit_price) || null : null,
        stop_price: form.order_type === "STOP_LOSS" ? parseFloat(form.stop_price) || null : null,
        algo_type: form.algo_type,
        account_id: form.account_id || undefined,
        start_time: form.start_time || undefined,
        end_time: form.end_time || undefined,
        tif: form.tif,
        urgency: form.urgency,
        get_done: form.get_done,
        capacity: form.capacity,
        order_notes: form.order_notes || undefined,
      };

      if (form.algo_type !== "NONE") {
        if (form.algo_type === "POV") {
          payload.algo_params = {
            target_participation_rate: parseFloat(form.target_participation_rate),
            min_order_size: parseInt(form.min_order_size),
            max_order_size: parseInt(form.max_order_size),
            aggression_level: form.aggression_level,
          };
        } else if (form.algo_type === "VWAP") {
          payload.algo_params = {
            volume_curve: form.volume_curve,
            max_volume_pct: parseFloat(form.max_volume_pct),
            aggression_level: form.aggression_level,
          };
        } else if (form.algo_type === "ICEBERG") {
          payload.algo_params = {
            display_quantity: parseInt(form.display_quantity),
            aggression_level: form.aggression_level,
          };
        }
      }

      const order = await ordersApi.create(payload);
      toast.success(`Order ${order.order_id} submitted`, {
        description: `${order.direction} ${order.quantity.toLocaleString()} ${order.symbol}`,
      });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      setShowConfirmation(false);
      onOpenChange(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to submit order";
      setErrors(message.split("; "));
      setShowConfirmation(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[95vw] sm:max-w-7xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2">
              <Send className="h-5 w-5" />
              New Order
              {prefillEnabled && prefilling && (
                <Badge variant="outline" className="ml-2 text-xs border-[oklch(0.68_0.15_240)]/40 text-[oklch(0.68_0.15_240)] animate-pulse">
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  Analyzing…
                </Badge>
              )}
              {prefillEnabled && prefill && !prefilling && prefilledFields.size > 0 && (
                <Badge variant="outline" className="ml-2 text-xs border-[oklch(0.68_0.15_240)]/40 text-[oklch(0.68_0.15_240)]">
                  <Sparkles className="h-3 w-3 mr-1" />
                  {prefilledFields.size} fields prefilled
                </Badge>
              )}
            </DialogTitle>
            <div className="flex items-center gap-2 mr-6">
              {prefillEnabled ? (
                <Zap className="h-4 w-4 text-[oklch(0.68_0.15_240)]" />
              ) : (
                <ZapOff className="h-4 w-4 text-muted-foreground" />
              )}
              <Label
                htmlFor="prefill-toggle"
                className={`text-xs font-medium cursor-pointer select-none ${
                  prefillEnabled ? "text-[oklch(0.68_0.15_240)]" : "text-muted-foreground"
                }`}
              >
                Smart Prefill
              </Label>
              <Switch
                id="prefill-toggle"
                checked={prefillEnabled}
                onCheckedChange={handlePrefillToggle}
                className="data-[state=checked]:bg-[oklch(0.68_0.15_240)]"
              />
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4">
          {/* Errors */}
          {errors.length > 0 && (
            <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <AlertTriangle className="h-4 w-4 text-rose-400" />
                <span className="text-sm font-medium text-rose-400">Validation Errors</span>
              </div>
              <ul className="text-sm text-rose-300 space-y-1">
                {errors.map((e, i) => (
                  <li key={i}>• {e}</li>
                ))}
              </ul>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════
              PREFILL SUMMARY CARD + URGENCY KNOB  (full-width banner)
             ═══════════════════════════════════════════════════════════ */}
          {prefillEnabled && prefill && !prefilling && form.client_id && form.symbol && (
            <div className="rounded-lg border border-[oklch(0.68_0.15_240)]/20 bg-[oklch(0.68_0.15_240)]/5 p-4 space-y-3">
              {/* Scenario badge + headline */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Target className="h-4 w-4 text-[oklch(0.68_0.15_240)]" />
                  <span className="text-sm font-semibold text-[oklch(0.68_0.15_240)]">
                    {prefill.scenario_label}
                  </span>
                  <Badge variant="outline" className="text-[10px] border-[oklch(0.68_0.15_240)]/30 text-[oklch(0.68_0.15_240)]">
                    {prefill.scenario_tag.replace(/_/g, " ")}
                  </Badge>
                </div>
                <Badge
                  variant="outline"
                  className={`text-xs ${uZone.color} border-current/30`}
                >
                  Urgency: {form.urgency}/100
                </Badge>
              </div>

              {/* Algo explanation summary */}
              {prefill.explanations.algo_type && (
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {prefill.explanations.algo_type}
                </p>
              )}

              {/* ── URGENCY META-SLIDER ── */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost" size="sm"
                      className="h-6 px-2 text-xs text-muted-foreground hover:text-emerald-400"
                      onClick={() => nudgeUrgency(-10)}
                      disabled={form.urgency <= 0}
                    >
                      <ChevronLeft className="h-3 w-3 mr-0.5" /> More Passive
                    </Button>
                  </div>
                  <span className={`text-xs font-bold ${uZone.color} inline-flex items-center gap-1`}>
                    {uZone.label}
                    {prefill && (
                      <TooltipProvider>
                        <Tooltip delayDuration={150}>
                          <TooltipTrigger asChild>
                            <button type="button" className="inline-flex items-center justify-center rounded-full focus:outline-none">
                              <Info className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="top" className="max-w-xs p-0 bg-popover text-popover-foreground border border-border shadow-lg rounded-lg">
                            <div className="px-3 py-2 border-b border-border">
                              <p className="text-[11px] font-semibold">Urgency Score Breakdown</p>
                            </div>
                            {prefill.urgency_breakdown && prefill.urgency_breakdown.length > 0 ? (
                              <>
                                <div className="px-3 py-2 space-y-1.5">
                                  {prefill.urgency_breakdown.map((item, i) => (
                                    <div key={i} className="flex items-center justify-between gap-4 text-[11px]">
                                      <div className="flex flex-col min-w-0">
                                        <span className="font-medium truncate">{item.factor}</span>
                                        <span className="text-[10px] text-muted-foreground truncate">{item.detail}</span>
                                      </div>
                                      <span className={`font-mono font-semibold shrink-0 ${
                                        item.delta > 0 ? "text-rose-400" : item.delta < 0 ? "text-emerald-400" : "text-muted-foreground"
                                      }`}>
                                        {item.delta > 0 ? "+" : ""}{item.delta}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                                <div className="px-3 py-1.5 border-t border-border flex justify-between text-[11px] font-semibold">
                                  <span>Final Score</span>
                                  <span className={uZone.color}>{prefill.computed_urgency}/100</span>
                                </div>
                              </>
                            ) : (
                              <div className="px-3 py-2 text-[11px] text-muted-foreground">
                                Urgency is computed from time pressure, client profile, order size, volatility, order notes, and risk aversion.
                              </div>
                            )}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost" size="sm"
                      className="h-6 px-2 text-xs text-muted-foreground hover:text-rose-400"
                      onClick={() => nudgeUrgency(10)}
                      disabled={form.urgency >= 100}
                    >
                      More Urgent <ChevronRight className="h-3 w-3 ml-0.5" />
                    </Button>
                  </div>
                </div>
                <div className="relative">
                  <Slider
                    value={[form.urgency]}
                    onValueChange={handleUrgencyChange}
                    min={0} max={100} step={1}
                    className="flex-1"
                  />
                  {/* Zone markers */}
                  <div className="flex justify-between mt-1 px-0.5">
                    <span className="text-[9px] text-emerald-500/60">Patient</span>
                    <span className="text-[9px] text-sky-500/60">Moderate</span>
                    <span className="text-[9px] text-violet-500/60">Balanced</span>
                    <span className="text-[9px] text-amber-500/60">Active</span>
                    <span className="text-[9px] text-rose-500/60">Urgent</span>
                  </div>
                </div>
                <p className="text-[10px] text-muted-foreground text-center">
                  Drag to adjust — all parameters cascade automatically
                  {prefill.computed_urgency !== form.urgency && (
                    <span className="ml-1 text-[oklch(0.68_0.15_240)]">
                      (system suggested {prefill.computed_urgency})
                    </span>
                  )}
                </p>
              </div>

              {/* Why-Not toggle */}
              <button
                onClick={() => setShowWhyNot(!showWhyNot)}
                className="text-[10px] text-muted-foreground hover:text-foreground underline underline-offset-2 transition-colors"
              >
                {showWhyNot ? "Hide" : "Show"} why other algorithms were not chosen
              </button>

              {/* Why-Not panel */}
              {showWhyNot && prefill.why_not && Object.keys(prefill.why_not).length > 0 && (
                <div className="rounded-md border border-muted/30 bg-muted/10 p-2.5 space-y-1.5">
                  {Object.entries(prefill.why_not).map(([algo, reason]) => (
                    <div key={algo} className="flex items-start gap-2 text-xs">
                      <XCircle className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                      <div>
                        <span className="font-medium text-muted-foreground">{algo}:</span>{" "}
                        <span className="text-muted-foreground/80">{reason}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════
              TWO-COLUMN LAYOUT: Left = Order Details, Right = Execution
             ═══════════════════════════════════════════════════════════ */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* ─── LEFT COLUMN: Core Order Details ─── */}
            <div className="space-y-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Order Details</h3>

              {/* Client + Symbol */}
              <div className="grid grid-cols-2 gap-3">
                <div className="min-w-0">
                  <Label>Counterparty *</Label>
                  <Select value={form.client_id} onValueChange={(v) => update("client_id", v)}>
                    <SelectTrigger className="w-full min-w-0">
                      <SelectValue placeholder="Select client" />
                    </SelectTrigger>
                    <SelectContent>
                      {clients.map((c) => (
                        <SelectItem key={c.client_id} value={c.client_id}>
                          {c.client_id} — {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="min-w-0">
                  <Label>Symbol *</Label>
                  <Select value={form.symbol} onValueChange={(v) => update("symbol", v)}>
                    <SelectTrigger className="w-full min-w-0">
                      <SelectValue placeholder="Select symbol" />
                    </SelectTrigger>
                    <SelectContent>
                      {instruments.map((i) => (
                        <SelectItem key={i.symbol} value={i.symbol}>
                          {i.symbol} — {i.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Account + Capacity */}
              {form.client_id && (
                <div className="grid grid-cols-2 gap-3">
                  {accounts.length > 0 && (
                    <div className="min-w-0">
                      <Label>Account</Label>
                      <Select value={form.account_id} onValueChange={(v) => update("account_id", v)}>
                        <SelectTrigger className="w-full min-w-0">
                          <SelectValue placeholder="Select account" />
                        </SelectTrigger>
                        <SelectContent>
                          {accounts.map((a) => (
                            <SelectItem key={a.account_id} value={a.account_id}>
                              {a.account_name} ({a.account_type}){a.is_default ? " ★" : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <div className="min-w-0">
                    <Label>Capacity</Label>
                    <Select value={form.capacity} onValueChange={(v) => update("capacity", v)}>
                      <SelectTrigger className="w-full min-w-0">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="AGENCY">Agency</SelectItem>
                        <SelectItem value="PRINCIPAL">Principal</SelectItem>
                        <SelectItem value="RISKLESS_PRINCIPAL">Riskless Principal</SelectItem>
                        <SelectItem value="MIXED">Mixed</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}

              {/* Direction + Order Type */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Direction *</Label>
                  <Select value={form.direction} onValueChange={(v) => update("direction", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="BUY">BUY</SelectItem>
                      <SelectItem value="SELL">SELL</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="flex items-center">Order Type *<PrefillHint field="order_type" /></Label>
                  <Select value={form.order_type} onValueChange={(v) => update("order_type", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="MARKET">Market</SelectItem>
                      <SelectItem value="LIMIT">Limit</SelectItem>
                      <SelectItem value="STOP_LOSS">Stop Loss</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Quantity + Limit/Stop price */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="flex items-center">Quantity *<PrefillHint field="quantity" /></Label>
                  <Input
                    type="number"
                    placeholder="e.g. 150000"
                    value={form.quantity}
                    onChange={(e) => update("quantity", e.target.value)}
                  />
                </div>
                {form.order_type === "LIMIT" && (
                  <div>
                    <Label className="flex items-center">Limit Price *<PrefillHint field="limit_price" /></Label>
                    <Input
                      type="number" step="0.05"
                      placeholder={symbolMd ? `LTP: ₹${symbolMd.ltp.toFixed(2)}` : ""}
                      value={form.limit_price}
                      onChange={(e) => update("limit_price", e.target.value)}
                    />
                    {symbolMd && (
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Collar: ₹{(symbolMd.ltp * 0.95).toFixed(2)} – ₹{(symbolMd.ltp * 1.05).toFixed(2)}
                      </p>
                    )}
                  </div>
                )}
                {form.order_type === "STOP_LOSS" && (
                  <div>
                    <Label>Stop Price *</Label>
                    <Input
                      type="number" step="0.05"
                      placeholder="Trigger price"
                      value={form.stop_price}
                      onChange={(e) => update("stop_price", e.target.value)}
                    />
                  </div>
                )}
              </div>

              {/* TIF + Get Done */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="flex items-center">Time In Force<PrefillHint field="tif" /></Label>
                  <Select value={form.tif} onValueChange={(v) => update("tif", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="GFD">GFD — Good For Day</SelectItem>
                      <SelectItem value="IOC">IOC — Immediate or Cancel</SelectItem>
                      <SelectItem value="FOK">FOK — Fill or Kill</SelectItem>
                      <SelectItem value="GTC">GTC — Good Till Cancel</SelectItem>
                      <SelectItem value="GTD">GTD — Good Till Date</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end pb-2">
                  <div className="flex items-center gap-2">
                    <Switch
                      id="get-done"
                      checked={form.get_done}
                      onCheckedChange={(v) => update("get_done", v)}
                    />
                    <Label htmlFor="get-done" className="flex items-center gap-1 cursor-pointer text-sm">
                      Get Done
                      <PrefillHint field="get_done" />
                    </Label>
                  </div>
                </div>
              </div>

              {/* Notional estimate + ADV % */}
              {notional > 0 && (
                <div className="flex items-center gap-2 text-sm flex-wrap">
                  <Info className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Est. Notional:</span>
                  <span className="font-mono font-semibold">
                    ₹{notional.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </span>
                  {advPct !== null && (
                    <>
                      <span className="text-muted-foreground">·</span>
                      <span className="text-muted-foreground">ADV:</span>
                      <span className={`font-mono font-semibold ${advPct > 20 ? "text-rose-400" : advPct > 10 ? "text-amber-400" : "text-emerald-400"}`}>
                        {advPct.toFixed(1)}%
                      </span>
                      {advPct > 20 && (
                        <Badge variant="outline" className="text-[10px] border-rose-500/50 bg-rose-500/10 text-rose-400">Large block</Badge>
                      )}
                    </>
                  )}
                  {selectedClient && notional > selectedClient.credit_limit && (
                    <Badge variant="destructive" className="text-xs">Exceeds credit limit</Badge>
                  )}
                </div>
              )}

              {/* Order Notes */}
              <div>
                <Label className="flex items-center">Order Notes<PrefillHint field="order_notes" /></Label>
                <Textarea
                  placeholder="Special instructions, compliance notes..."
                  value={form.order_notes}
                  onChange={(e) => update("order_notes", e.target.value)}
                  rows={2}
                />
              </div>
            </div>

            {/* ─── RIGHT COLUMN: Market Data + Execution Strategy ─── */}
            <div className="space-y-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Execution Strategy</h3>

              {/* Market data snapshot */}
              {symbolMd && (
                <div className="bg-muted/50 rounded-lg p-3 grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <span className="text-muted-foreground text-xs">LTP</span>
                    <p className="font-mono font-semibold">₹{symbolMd.ltp.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Bid</span>
                    <p className="font-mono">₹{symbolMd.bid.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Ask</span>
                    <p className="font-mono">₹{symbolMd.ask.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Spread</span>
                    <p className="font-mono">{symbolMd.spread_bps.toFixed(1)} bps</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Vol</span>
                    <p className="font-mono">{symbolMd.volatility.toFixed(2)}%</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">To Close</span>
                    <p className="font-mono">{symbolMd.time_to_close}m</p>
                  </div>
                </div>
              )}

              {/* Risk Aversion Slider */}
              {form.client_id && (
                <div className="bg-muted/30 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="flex items-center gap-1.5 text-sm">
                      <Gauge className="h-4 w-4 text-[oklch(0.68_0.15_240)]" />
                      Risk Profile
                    </Label>
                    <Badge
                      variant="outline"
                      className={
                        riskAversion >= 70
                          ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400 text-xs"
                          : riskAversion <= 29
                          ? "border-rose-500/50 bg-rose-500/10 text-rose-400 text-xs"
                          : "border-[oklch(0.68_0.15_240)]/50 bg-[oklch(0.68_0.15_240)]/10 text-[oklch(0.68_0.15_240)] text-xs"
                      }
                    >
                      {riskLabel} ({riskAversion})
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] text-rose-400 font-medium w-16 shrink-0">Aggressive</span>
                    <Slider
                      value={[riskAversion]}
                      onValueChange={(v) => setRiskAversion(v[0])}
                      min={0} max={100} step={1}
                      className="flex-1"
                    />
                    <span className="text-[10px] text-emerald-400 font-medium w-20 shrink-0 text-right">Conservative</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    Inherited from client profile. Adjust to override for this order.
                  </p>
                </div>
              )}

              <Separator />

              {/* Algo Selection */}
              <div>
                <Label className="flex items-center">Execution Algorithm<PrefillHint field="algo_type" /></Label>
                <Select value={form.algo_type} onValueChange={(v) => update("algo_type", v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="NONE">Direct (No Algo)</SelectItem>
                    <SelectItem value="POV">POV — Percentage of Volume</SelectItem>
                    <SelectItem value="VWAP">VWAP — Volume Weighted Avg Price</SelectItem>
                    <SelectItem value="ICEBERG">ICEBERG — Hidden Quantity</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Algo Time Window */}
              {form.algo_type !== "NONE" && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="flex items-center">Start Time *<PrefillHint field="start_time" /></Label>
                    <Input type="time" value={form.start_time} onChange={(e) => update("start_time", e.target.value)} />
                  </div>
                  <div>
                    <Label className="flex items-center">End Time *<PrefillHint field="end_time" /></Label>
                    <Input type="time" value={form.end_time} onChange={(e) => update("end_time", e.target.value)} />
                  </div>
                </div>
              )}

              {/* POV Params */}
              {form.algo_type === "POV" && (
                <div className="bg-muted/30 rounded-lg p-3 space-y-3">
                  <h4 className="text-sm font-semibold">POV Parameters</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-xs flex items-center">Target Part. %<PrefillHint field="target_participation_rate" /></Label>
                      <Input type="number" min="1" max="50" value={form.target_participation_rate} onChange={(e) => update("target_participation_rate", e.target.value)} />
                    </div>
                    <div>
                      <Label className="text-xs flex items-center">Aggression<PrefillHint field="aggression_level" /></Label>
                      <Select value={form.aggression_level} onValueChange={(v) => update("aggression_level", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Low">Low — Passive</SelectItem>
                          <SelectItem value="Medium">Medium — Balanced</SelectItem>
                          <SelectItem value="High">High — Aggressive</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-xs flex items-center">Min Order Size<PrefillHint field="min_order_size" /></Label>
                      <Input type="number" value={form.min_order_size} onChange={(e) => update("min_order_size", e.target.value)} />
                    </div>
                    <div>
                      <Label className="text-xs flex items-center">Max Order Size<PrefillHint field="max_order_size" /></Label>
                      <Input type="number" value={form.max_order_size} onChange={(e) => update("max_order_size", e.target.value)} />
                    </div>
                  </div>
                </div>
              )}

              {/* VWAP Params */}
              {form.algo_type === "VWAP" && (
                <div className="bg-muted/30 rounded-lg p-3 space-y-3">
                  <h4 className="text-sm font-semibold">VWAP Parameters</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-xs flex items-center">Volume Curve<PrefillHint field="volume_curve" /></Label>
                      <Select value={form.volume_curve} onValueChange={(v) => update("volume_curve", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Historical">Historical</SelectItem>
                          <SelectItem value="Front-loaded">Front-loaded</SelectItem>
                          <SelectItem value="Back-loaded">Back-loaded</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label className="text-xs flex items-center">Max Volume %<PrefillHint field="max_volume_pct" /></Label>
                      <Input type="number" min="1" max="50" value={form.max_volume_pct} onChange={(e) => update("max_volume_pct", e.target.value)} />
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs flex items-center">Aggression Level<PrefillHint field="aggression_level" /></Label>
                    <Select value={form.aggression_level} onValueChange={(v) => update("aggression_level", v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Low">Low — Passive</SelectItem>
                        <SelectItem value="Medium">Medium — Balanced</SelectItem>
                        <SelectItem value="High">High — Aggressive</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}

              {/* ICEBERG Params */}
              {form.algo_type === "ICEBERG" && (
                <div className="bg-muted/30 rounded-lg p-3 space-y-3">
                  <h4 className="text-sm font-semibold">ICEBERG Parameters</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-xs flex items-center">Display Quantity<PrefillHint field="display_quantity" /></Label>
                      <Input type="number" placeholder="Visible qty" value={form.display_quantity} onChange={(e) => update("display_quantity", e.target.value)} />
                      <p className="text-[10px] text-muted-foreground mt-1">Must be less than total order size</p>
                    </div>
                    <div>
                      <Label className="text-xs flex items-center">Aggression Level<PrefillHint field="aggression_level" /></Label>
                      <Select value={form.aggression_level} onValueChange={(v) => update("aggression_level", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Low">Low — Passive</SelectItem>
                          <SelectItem value="Medium">Medium — Balanced</SelectItem>
                          <SelectItem value="High">High — Aggressive</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !form.client_id || !form.symbol || !form.quantity}
            className={
              form.direction === "BUY"
                ? "bg-emerald-600 hover:bg-emerald-700"
                : "bg-rose-600 hover:bg-rose-700"
            }
          >
            {submitting ? "Submitting..." : `${form.direction} ${form.symbol || "..."}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <OrderConfirmationDialog
      open={showConfirmation}
      onOpenChange={setShowConfirmation}
      data={{
        client_name: selectedClient?.name ?? form.client_id,
        account_name: selectedAccount?.account_name ?? null,
        symbol: form.symbol,
        direction: form.direction,
        order_type: form.order_type,
        quantity: parseInt(form.quantity) || 0,
        limit_price: form.order_type === "LIMIT" ? parseFloat(form.limit_price) || null : null,
        algo_type: form.algo_type,
        aggression: form.algo_type !== "NONE" ? form.aggression_level : undefined,
        tif: form.tif,
        urgency: form.urgency,
        get_done: form.get_done,
        capacity: form.capacity,
        estimated_value: notional > 0 ? notional : null,
      }}
      onConfirm={executeOrder}
      isSubmitting={submitting}
    />
    </>
  );
}
