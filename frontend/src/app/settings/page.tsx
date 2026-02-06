"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ruleConfigApi } from "@/lib/api";
import type { RuleConfigItem } from "@/lib/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Settings,
  ArrowLeft,
  Save,
  RotateCcw,
  Info,
  Check,
  AlertTriangle,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

// ── Category metadata ──────────────────────────────────────────────

const CATEGORY_META: Record<
  string,
  { label: string; description: string; icon: string }
> = {
  urgency: {
    label: "Urgency Scoring",
    description:
      "Controls the urgency score — the master variable that cascades to all other parameters.",
    icon: "🎯",
  },
  algo: {
    label: "Algo Selection",
    description:
      "Thresholds for algo type selection based on urgency, order size, and client tags.",
    icon: "🤖",
  },
  order_type: {
    label: "Order Type",
    description: "Thresholds for MARKET vs LIMIT order type decisions.",
    icon: "📋",
  },
  limit_price: {
    label: "Limit Price",
    description:
      "Basis-point offsets applied to LTP when calculating the limit price.",
    icon: "💰",
  },
  tif: {
    label: "Time In Force",
    description: "Urgency thresholds for TIF (IOC, FOK, GFD, GTC) selection.",
    icon: "⏱️",
  },
  time_window: {
    label: "Time Window",
    description:
      "Controls how the algo execution window is sized based on urgency.",
    icon: "📐",
  },
  aggression: {
    label: "Aggression",
    description:
      "Aggression level (Low / Medium / High) thresholds driven by urgency and risk aversion.",
    icon: "⚡",
  },
  pov: {
    label: "POV Params",
    description:
      "POV algorithm participation rates and child-order sizing rules.",
    icon: "📊",
  },
  vwap: {
    label: "VWAP Params",
    description: "VWAP volume-curve selection and per-interval limits.",
    icon: "📈",
  },
  iceberg: {
    label: "ICEBERG Params",
    description: "ICEBERG display-quantity calculation parameters.",
    icon: "🧊",
  },
  historical: {
    label: "Historical Blending",
    description:
      "Controls how past client–symbol trading patterns are blended with rules.",
    icon: "📚",
  },
  cross_client: {
    label: "Cross-Client",
    description:
      "Cross-client pattern-signal thresholds (non-overriding, informational).",
    icon: "🔗",
  },
  scenario: {
    label: "Scenario Detection",
    description:
      "Thresholds for labelling orders as EOD Compliance, Stealth, Speed Priority, etc.",
    icon: "🏷️",
  },
  get_done: {
    label: "Get Done",
    description: "Get-done flag activation thresholds.",
    icon: "✅",
  },
};

const CATEGORY_ORDER = [
  "urgency",
  "algo",
  "order_type",
  "limit_price",
  "tif",
  "time_window",
  "aggression",
  "pov",
  "vwap",
  "iceberg",
  "historical",
  "cross_client",
  "scenario",
  "get_done",
];

// ── Helpers ─────────────────────────────────────────────────────────

function formatValue(val: number, dataType: string): string {
  if (dataType === "integer") return String(Math.round(val));
  return String(parseFloat(val.toFixed(4)));
}

function displayUnit(unit: string): string {
  if (!unit || unit === "fraction") return "";
  return unit;
}

// ── Component ───────────────────────────────────────────────────────

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("urgency");
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);

  // Fetch all configs
  const {
    data: allConfigs,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["rule-config"],
    queryFn: ruleConfigApi.getAll,
  });

  // Group by category
  const byCategory: Record<string, RuleConfigItem[]> = {};
  for (const item of allConfigs ?? []) {
    if (!byCategory[item.category]) byCategory[item.category] = [];
    byCategory[item.category].push(item);
  }
  // Sort each group by display_order
  for (const cat of Object.keys(byCategory)) {
    byCategory[cat].sort((a, b) => a.display_order - b.display_order);
  }

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (updates: { key: string; value: number }[]) =>
      ruleConfigApi.updateMany(updates),
    onSuccess: (data) => {
      toast.success(`Saved ${data.updated} configuration values`);
      setEdits({});
      refetch();
    },
    onError: (err: Error) => {
      toast.error(`Failed to save: ${err.message}`);
    },
  });

  // Reset mutation
  const resetMutation = useMutation({
    mutationFn: ruleConfigApi.resetToDefaults,
    onSuccess: () => {
      toast.success("All configurations reset to factory defaults");
      setEdits({});
      refetch();
    },
    onError: (err: Error) => {
      toast.error(`Failed to reset: ${err.message}`);
    },
  });

  // Count unsaved changes for current tab
  const currentItems = byCategory[activeTab] ?? [];
  const unsavedCount = currentItems.filter((item) =>
    edits[item.key] !== undefined && edits[item.key] !== item.value
  ).length;
  const totalUnsaved = Object.keys(edits).length;

  const handleValueChange = (key: string, rawValue: string, original: number) => {
    const parsed = parseFloat(rawValue);
    if (isNaN(parsed)) return;
    if (parsed === original) {
      // Remove from edits if back to original
      setEdits((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } else {
      setEdits((prev) => ({ ...prev, [key]: parsed }));
    }
  };

  const handleSaveCategory = () => {
    const updates = currentItems
      .filter((item) => edits[item.key] !== undefined && edits[item.key] !== item.value)
      .map((item) => ({ key: item.key, value: edits[item.key] }));
    if (updates.length === 0) return;
    saveMutation.mutate(updates);
  };

  const handleSaveAll = () => {
    const updates = Object.entries(edits).map(([key, value]) => ({
      key,
      value,
    }));
    if (updates.length === 0) return;
    saveMutation.mutate(updates);
  };

  const handleReset = () => {
    if (
      !confirm(
        "Reset ALL configurations across ALL categories to factory defaults? This cannot be undone."
      )
    )
      return;
    resetMutation.mutate();
  };

  const getEffectiveValue = (item: RuleConfigItem): number => {
    return edits[item.key] !== undefined ? edits[item.key] : item.value;
  };

  const isModified = (item: RuleConfigItem): boolean => {
    return edits[item.key] !== undefined && edits[item.key] !== item.value;
  };

  const isOutOfRange = (item: RuleConfigItem): boolean => {
    const val = getEffectiveValue(item);
    if (item.min_value !== null && val < item.min_value) return true;
    if (item.max_value !== null && val > item.max_value) return true;
    return false;
  };

  return (
    <TooltipProvider delayDuration={200} skipDelayDuration={500}>
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
              <Settings className="h-4 w-4 text-white" />
            </div>
            <h1 className="text-lg font-bold tracking-tight text-white">
              Rule Engine Configuration
            </h1>
            <Badge
              variant="outline"
              className="text-xs border-[oklch(0.68_0.15_240)]/40 text-[oklch(0.68_0.15_240)]"
            >
              {allConfigs?.length ?? 0} parameters
            </Badge>
            {totalUnsaved > 0 && (
              <Badge className="text-xs bg-amber-500/20 text-amber-400 border-amber-500/40">
                {totalUnsaved} unsaved
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-2">
            {totalUnsaved > 0 && (
              <Button
                onClick={handleSaveAll}
                size="sm"
                className="bg-emerald-600 hover:bg-emerald-700 text-white"
                disabled={saveMutation.isPending}
              >
                <Save className="h-4 w-4 mr-1" />
                Save All ({totalUnsaved})
              </Button>
            )}
            <Button
              onClick={handleReset}
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-red-400"
              disabled={resetMutation.isPending}
            >
              <RotateCcw className="h-4 w-4 mr-1" />
              Reset Defaults
            </Button>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 p-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-64 text-muted-foreground">
              Loading configuration...
            </div>
          ) : (
            <Tabs
              value={activeTab}
              onValueChange={setActiveTab}
              className="space-y-4"
            >
              <TabsList className="bg-[oklch(0.12_0.06_255)] border border-border/50 flex-wrap h-auto py-1 gap-0.5">
                {CATEGORY_ORDER.filter((c) => byCategory[c]).map((cat) => {
                  const meta = CATEGORY_META[cat];
                  const catEdits = (byCategory[cat] ?? []).filter(
                    (item) =>
                      edits[item.key] !== undefined &&
                      edits[item.key] !== item.value
                  ).length;
                  return (
                    <TabsTrigger
                      key={cat}
                      value={cat}
                      className="text-xs gap-1 px-2.5"
                    >
                      <span className="text-[10px]">{meta?.icon}</span>
                      {meta?.label ?? cat}
                      {catEdits > 0 && (
                        <Badge className="ml-1 text-[9px] px-1 py-0 bg-amber-500/20 text-amber-400 border-amber-500/40">
                          {catEdits}
                        </Badge>
                      )}
                    </TabsTrigger>
                  );
                })}
              </TabsList>

              {CATEGORY_ORDER.filter((c) => byCategory[c]).map((cat) => {
                const meta = CATEGORY_META[cat];
                const items = byCategory[cat] ?? [];
                const catUnsaved = items.filter(
                  (item) =>
                    edits[item.key] !== undefined &&
                    edits[item.key] !== item.value
                ).length;

                return (
                  <TabsContent key={cat} value={cat} className="space-y-4">
                    {/* Category header */}
                    <div className="flex items-start justify-between">
                      <div>
                        <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                          <span>{meta?.icon}</span>
                          {meta?.label ?? cat}
                          <Badge
                            variant="outline"
                            className="text-[10px] text-muted-foreground border-border/50"
                          >
                            {items.length} values
                          </Badge>
                        </h2>
                        <p className="text-sm text-muted-foreground mt-0.5">
                          {meta?.description}
                        </p>
                      </div>
                      {catUnsaved > 0 && (
                        <Button
                          onClick={handleSaveCategory}
                          size="sm"
                          className="bg-emerald-600 hover:bg-emerald-700 text-white"
                          disabled={saveMutation.isPending}
                        >
                          <Save className="h-4 w-4 mr-1" />
                          Save {meta?.label} ({catUnsaved})
                        </Button>
                      )}
                    </div>

                    {/* Config grid */}
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                      {items.map((item) => {
                        const modified = isModified(item);
                        const outOfRange = isOutOfRange(item);
                        const effectiveVal = getEffectiveValue(item);

                        return (
                          <div
                            key={item.key}
                            className={`rounded-lg border p-3 transition-colors ${
                              modified
                                ? "border-amber-500/50 bg-amber-500/5"
                                : "border-border/50 bg-[oklch(0.12_0.06_255)]"
                            }`}
                          >
                            <div className="flex items-start justify-between mb-2">
                              <div className="flex items-center gap-1.5">
                                <Label className="text-sm font-medium text-foreground leading-tight">
                                  {item.label}
                                </Label>
                                <Tooltip disableHoverableContent={false}>
                                  <TooltipTrigger asChild>
                                    <button
                                      type="button"
                                      className="inline-flex items-center justify-center h-5 w-5 rounded hover:bg-muted/40 flex-shrink-0"
                                    >
                                      <Info className="h-3.5 w-3.5 text-muted-foreground/50 hover:text-muted-foreground cursor-help" />
                                    </button>
                                  </TooltipTrigger>
                                  <TooltipContent
                                    side="top"
                                    align="start"
                                    className="max-w-xs"
                                    onPointerDownOutside={(e) => e.preventDefault()}
                                  >
                                    <p className="text-xs">{item.description}</p>
                                    <p className="text-[10px] text-muted-foreground mt-1 font-mono">
                                      key: {item.key}
                                    </p>
                                  </TooltipContent>
                                </Tooltip>
                              </div>
                              {modified && (
                                <Badge className="text-[9px] px-1 py-0 bg-amber-500/20 text-amber-400 border-amber-500/40 flex-shrink-0">
                                  modified
                                </Badge>
                              )}
                            </div>

                            <div className="flex items-center gap-2">
                              <Input
                                type="number"
                                step={
                                  item.data_type === "integer" ? "1" : "0.01"
                                }
                                value={formatValue(
                                  effectiveVal,
                                  item.data_type
                                )}
                                onChange={(e) =>
                                  handleValueChange(
                                    item.key,
                                    e.target.value,
                                    item.value
                                  )
                                }
                                className={`h-8 text-sm font-mono bg-background/50 ${
                                  outOfRange
                                    ? "border-red-500/50 focus-visible:ring-red-500/30"
                                    : modified
                                    ? "border-amber-500/50 focus-visible:ring-amber-500/30"
                                    : "border-border/50"
                                }`}
                              />
                              {displayUnit(item.unit) && (
                                <Badge
                                  variant="outline"
                                  className="text-[10px] px-1.5 py-0 text-muted-foreground border-border/40 flex-shrink-0 whitespace-nowrap"
                                >
                                  {displayUnit(item.unit)}
                                </Badge>
                              )}
                            </div>

                            {/* Range hint */}
                            <div className="flex items-center justify-between mt-1.5">
                              <span className="text-[10px] text-muted-foreground/60">
                                {item.min_value !== null &&
                                  item.max_value !== null &&
                                  `Range: ${item.min_value} – ${item.max_value}`}
                              </span>
                              {outOfRange && (
                                <span className="text-[10px] text-red-400 flex items-center gap-0.5">
                                  <AlertTriangle className="h-3 w-3" />
                                  Out of range
                                </span>
                              )}
                              {modified && !outOfRange && (
                                <span className="text-[10px] text-muted-foreground/60">
                                  was: {formatValue(item.value, item.data_type)}
                                </span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </TabsContent>
                );
              })}
            </Tabs>
          )}
        </main>
      </div>
    </TooltipProvider>
  );
}
