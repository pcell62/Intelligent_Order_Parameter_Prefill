"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  BarChart3,
  Plus,
  Activity,
  Database,
} from "lucide-react";
import Link from "next/link";

interface NavbarProps {
  onNewOrder: () => void;
}

export function Navbar({ onNewOrder }: NavbarProps) {
  return (
    <header className="border-b border-border/50 bg-[oklch(0.12_0.06_255)] px-4 py-2 flex items-center justify-between shadow-lg shadow-black/20">
      <div className="flex items-center gap-3">
        <div className="h-7 w-7 rounded bg-[oklch(0.68_0.15_240)] flex items-center justify-center">
          <BarChart3 className="h-4 w-4 text-white" />
        </div>
        <h1 className="text-lg font-bold tracking-tight text-white">
          ION Trading
        </h1>
        <Badge variant="outline" className="text-xs border-[oklch(0.68_0.15_240)]/40 text-[oklch(0.68_0.15_240)]">
          <Activity className="h-3 w-3 mr-1" />
          NSE
        </Badge>
      </div>

      <div className="flex items-center gap-2">
        <Link href="/analytics">
          <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground">
            <Database className="h-4 w-4 mr-1" />
            Analytics
          </Button>
        </Link>
        <Button onClick={onNewOrder} size="sm" className="bg-[oklch(0.68_0.15_240)] hover:bg-[oklch(0.60_0.15_240)] text-white">
          <Plus className="h-4 w-4 mr-1" />
          New Order
        </Button>
      </div>
    </header>
  );
}
