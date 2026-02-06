"use client";

import { useRef, useEffect, useCallback } from "react";
import type { Candlestick } from "@/lib/types";
import type { UTCTimestamp } from "lightweight-charts";

interface CandlestickChartProps {
  data: Candlestick[];
  symbol: string;
}

export function CandlestickChart({ data, symbol }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);

  const initChart = useCallback(async () => {
    if (!containerRef.current) return;

    // Dynamic import to avoid SSR issues (v5 API)
    const lc = await import("lightweight-charts");

    // Dispose old chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = lc.createChart(containerRef.current, {
      layout: {
        background: { type: lc.ColorType.Solid, color: "#001437" },
        textColor: "#8899b0",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#0a2240" },
        horzLines: { color: "#0a2240" },
      },
      crosshair: {
        mode: lc.CrosshairMode.Normal,
        vertLine: { color: "#4a90d9", width: 1, style: 2 },
        horzLine: { color: "#4a90d9", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "#122a4a",
      },
      timeScale: {
        borderColor: "#122a4a",
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: 500,
    });

    // v5: addSeries(SeriesType, options)
    const candleSeries = chart.addSeries(lc.CandlestickSeries, {
      upColor: "#34d399",
      downColor: "#fb7185",
      borderDownColor: "#fb7185",
      borderUpColor: "#34d399",
      wickDownColor: "#fb7185",
      wickUpColor: "#34d399",
    });

    const volumeSeries = chart.addSeries(lc.HistogramSeries, {
      color: "#4a90d9",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    if (data.length > 0) {
      candleSeries.setData(
        data.map((d) => ({
          time: d.time as UTCTimestamp,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
      );

      volumeSeries.setData(
        data.map((d) => ({
          time: d.time as UTCTimestamp,
          value: d.volume,
          color:
            d.close >= d.open
              ? "rgba(52, 211, 153, 0.3)"
              : "rgba(251, 113, 133, 0.3)",
        }))
      );

      chart.timeScale().fitContent();
    }

    chartRef.current = chart;

    // Resize handler
    const resizeObserver = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      chart.applyOptions({ width });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [data]);

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    initChart().then((c) => {
      cleanup = c;
    });
    return () => {
      cleanup?.();
    };
  }, [initChart]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="font-semibold text-foreground">{symbol}</span>
        {data.length > 0 && (
          <>
            <span>·</span>
            <span>{data.length} candles</span>
            <span>·</span>
            <span>
              Last: ₹{data[data.length - 1].close.toFixed(2)}
            </span>
          </>
        )}
      </div>
      <div
        ref={containerRef}
        className="rounded-lg border border-border/50 overflow-hidden"
        style={{ height: 500 }}
      />
    </div>
  );
}
