"use client";

import { useState, useMemo } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
} from "lucide-react";

interface DatabaseTableProps<T extends Record<string, unknown>> {
  data: T[];
  columns?: string[];
  /** For paginated endpoints */
  totalRows?: number;
  page?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
  pageSize?: number;
}

type SortDir = "asc" | "desc" | null;

export function DatabaseTable<T extends Record<string, unknown>>({
  data,
  columns: columnsProp,
  totalRows,
  page,
  totalPages,
  onPageChange,
  pageSize,
}: DatabaseTableProps<T>) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [filter, setFilter] = useState("");

  // Derive columns from first row if not supplied
  const columns = useMemo(() => {
    if (columnsProp) return columnsProp;
    if (data.length === 0) return [];
    return Object.keys(data[0]);
  }, [columnsProp, data]);

  // Filter + sort (client-side for non-paginated tables)
  const processed = useMemo(() => {
    let rows = [...data];

    // Text filter across all columns
    if (filter) {
      const lf = filter.toLowerCase();
      rows = rows.filter((row) =>
        columns.some((col) =>
          String(row[col] ?? "")
            .toLowerCase()
            .includes(lf)
        )
      );
    }

    // Sort
    if (sortCol && sortDir) {
      rows.sort((a, b) => {
        const va = a[sortCol] ?? "";
        const vb = b[sortCol] ?? "";
        if (typeof va === "number" && typeof vb === "number") {
          return sortDir === "asc" ? va - vb : vb - va;
        }
        const sa = String(va);
        const sb = String(vb);
        return sortDir === "asc"
          ? sa.localeCompare(sb)
          : sb.localeCompare(sa);
      });
    }

    return rows;
  }, [data, columns, filter, sortCol, sortDir]);

  const handleSort = (col: string) => {
    if (sortCol === col) {
      if (sortDir === "asc") setSortDir("desc");
      else if (sortDir === "desc") {
        setSortCol(null);
        setSortDir(null);
      }
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  const SortIcon = ({ col }: { col: string }) => {
    if (sortCol !== col)
      return <ArrowUpDown className="h-3 w-3 ml-1 opacity-40" />;
    if (sortDir === "asc")
      return <ArrowUp className="h-3 w-3 ml-1 text-[oklch(0.68_0.15_240)]" />;
    return <ArrowDown className="h-3 w-3 ml-1 text-[oklch(0.68_0.15_240)]" />;
  };

  const formatCell = (value: unknown): string => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "number") {
      if (Number.isInteger(value)) return value.toLocaleString();
      return value.toFixed(4);
    }
    return String(value);
  };

  const statusColor = (val: string) => {
    const v = val.toUpperCase();
    if (v === "FILLED") return "text-emerald-400";
    if (v === "WORKING" || v === "PARTIALLY_FILLED") return "text-[oklch(0.68_0.15_240)]";
    if (v === "CANCELLED" || v === "REJECTED") return "text-rose-400";
    if (v === "PENDING" || v === "VALIDATED") return "text-yellow-400";
    return "";
  };

  const isPaginated = totalPages !== undefined && onPageChange !== undefined;

  return (
    <div className="space-y-3">
      {/* Search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter rows…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-9 h-8 bg-[oklch(0.12_0.06_255)] border-border/50"
          />
        </div>
        <Badge variant="outline" className="text-xs text-muted-foreground">
          {totalRows !== undefined ? totalRows.toLocaleString() : processed.length} rows
        </Badge>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border/50 overflow-hidden">
        <div className="max-h-[60vh] overflow-auto">
          <Table>
            <TableHeader className="bg-[oklch(0.12_0.06_255)] sticky top-0 z-10">
              <TableRow className="hover:bg-transparent border-border/50">
                {columns.map((col) => (
                  <TableHead
                    key={col}
                    className="text-xs font-semibold text-muted-foreground uppercase tracking-wider cursor-pointer select-none"
                    onClick={() => handleSort(col)}
                  >
                    <div className="flex items-center">
                      {col.replace(/_/g, " ")}
                      <SortIcon col={col} />
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {processed.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="text-center text-muted-foreground py-8"
                  >
                    No data available
                  </TableCell>
                </TableRow>
              ) : (
                processed.map((row, i) => (
                  <TableRow
                    key={i}
                    className="border-border/30 hover:bg-[oklch(0.16_0.04_255)]"
                  >
                    {columns.map((col) => {
                      const val = row[col];
                      const formatted = formatCell(val);
                      const isStatus = col === "status";
                      return (
                        <TableCell
                          key={col}
                          className={`text-xs font-mono ${
                            isStatus ? statusColor(formatted) : ""
                          } ${
                            col === "direction" && typeof val === "string"
                              ? val === "BUY"
                                ? "text-emerald-400"
                                : "text-rose-400"
                              : ""
                          }`}
                        >
                          {formatted}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Pagination controls */}
      {isPaginated && totalPages > 0 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            Page {page} of {totalPages}
            {pageSize && totalRows !== undefined && (
              <> · Showing {Math.min(pageSize, processed.length)} of {totalRows.toLocaleString()}</>
            )}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page === 1}
              onClick={() => onPageChange(1)}
            >
              <ChevronsLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page === 1}
              onClick={() => onPageChange(page! - 1)}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page === totalPages}
              onClick={() => onPageChange(page! + 1)}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page === totalPages}
              onClick={() => onPageChange(totalPages)}
            >
              <ChevronsRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
