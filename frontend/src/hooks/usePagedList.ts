import { useEffect, useRef, useState } from "react";
import { api, qs } from "../services/api";
import type { Page } from "../types";
import { useAsync } from "./useAsync";
import type { AsyncState } from "./useAsync";

export interface PagedList<T> {
  state: AsyncState<Page<T>>;
  offset: number;
  setOffset: (n: number) => void;
  sort: string;
  order: "asc" | "desc";
  toggleSort: (column: string) => void;
}

/** Server-side pagination, sorting and filtering for a list endpoint. Offset resets when filters change. */
export function usePagedList<T>(
  path: string,
  filters: Record<string, string | number | undefined | null>,
  options: { pageSize?: number; defaultSort?: string; defaultOrder?: "asc" | "desc"; refreshKey?: number } = {},
): PagedList<T> {
  const pageSize = options.pageSize ?? 15;
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState(options.defaultSort ?? "");
  const [order, setOrder] = useState<"asc" | "desc">(options.defaultOrder ?? "desc");
  const key = JSON.stringify(filters);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) first.current = false;
    else setOffset(0);
  }, [key]);
  const state = useAsync(
    () => api<Page<T>>(`${path}${qs({ ...filters, limit: pageSize, offset, sort: sort || undefined, order: sort ? order : undefined })}`),
    [path, key, offset, sort, order, pageSize, options.refreshKey],
  );
  const toggleSort = (column: string) => {
    if (sort === column) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(column);
      setOrder("asc");
    }
    setOffset(0);
  };
  return { state, offset, setOffset, sort, order, toggleSort };
}
