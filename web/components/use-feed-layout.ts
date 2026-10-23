"use client";
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { feedLayout } from "../lib/feed-layout";
export function useFeedLayout(
  items: readonly { id: string }[],
  compact: boolean,
  viewport: RefObject<HTMLDivElement | null>,
  estimate: number,
  scroll: number,
  height: number,
  overscan: number,
) {
  const sizes = useRef(new Map<string, number>());
  const [revision, setRevision] = useState(0);
  const ids = useMemo(() => items.map((x) => x.id), [items]);
  useEffect(() => {
    const allowed = new Set(ids);
    for (const id of sizes.current.keys())
      if (!allowed.has(id)) sizes.current.delete(id);
  }, [ids]);
  useEffect(() => {
    const root = viewport.current;
    if (!root || !compact) return;
    let width = root.clientWidth;
    let frame = 0;
    let disposed = false;
    const notify = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!disposed) setRevision((x) => x + 1);
      });
    };
    const observer = new ResizeObserver((entries) => {
      let changed = false;
      for (const entry of entries) {
        const el = entry.target as HTMLElement;
        if (el === root) {
          if (root.clientWidth !== width) {
            width = root.clientWidth;
            sizes.current.clear();
            changed = true;
          }
          continue;
        }
        const id = el.dataset.rowId;
        const size = Math.ceil(el.getBoundingClientRect().height);
        if (id && size > 0 && sizes.current.get(id) !== size) {
          sizes.current.set(id, size);
          changed = true;
        }
      }
      if (changed) notify();
    });
    const observed = new Set<Element>();
    const scan = () => {
      const current = new Set(root.querySelectorAll("[data-row-id]"));
      for (const el of observed)
        if (!current.has(el)) {
          observer.unobserve(el);
          observed.delete(el);
        }
      for (const el of current)
        if (!observed.has(el)) {
          observed.add(el);
          observer.observe(el);
        }
    };
    observer.observe(root);
    scan();
    const mutations = new MutationObserver(scan);
    mutations.observe(root, { childList: true, subtree: true });
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      mutations.disconnect();
    };
  }, [compact, viewport, ids]);
  return useMemo(
    () =>
      feedLayout(
        ids,
        compact ? sizes.current : new Map(),
        estimate,
        scroll,
        height,
        overscan,
      ),
    [ids, compact, estimate, scroll, height, overscan, revision],
  );
}
