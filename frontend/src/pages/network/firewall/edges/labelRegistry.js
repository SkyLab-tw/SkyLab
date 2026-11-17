/**
 * 同一張畫布上常駐標籤的位置登記，讓標籤彼此避開。
 *
 * 每條線各自算標籤位置，互相看不到對方，兩個標籤被節點擠到同一塊空地時就會疊在一起。
 * 這裡依連線順序「先到先排」：每個標籤只把排在自己前面的標籤當障礙，
 * 排好後登記自己的範圍給後面的看。只依賴前面的，不會互相推來推去、一定收斂。
 *
 * 只有常駐顯示的標籤會登記；滑過才浮出的標籤自己會避開別人，但不該把別人推走。
 */

import { useLayoutEffect, useRef, useSyncExternalStore } from "react";
import { useStoreApi } from "@xyflow/react";

/* 一張畫布（一個 ReactFlow store）一份 */
const registries = new WeakMap();

const sameRect = (a, b) => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;

function registryFor(store) {
  let registry = registries.get(store);
  if (!registry) {
    const entries = new Map(); // edge id → { rank, rect }
    const listeners = new Set();
    registry = {
      entries,
      publish(id, entry) {
        const prev = entries.get(id);
        if (!prev && !entry) return;
        if (prev && entry && prev.rank === entry.rank && sameRect(prev.rect, entry.rect)) return;
        if (entry) entries.set(id, entry);
        else entries.delete(id);
        for (const listener of listeners) listener();
      },
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    };
    registries.set(store, registry);
  }
  return registry;
}

/**
 * 排在這條線前面（rank 較小）的常駐標籤範圍。
 * 只有這些變了才觸發重繪，後面的標籤怎麼動都不影響自己。
 */
export function useEarlierLabelRects(id, rank) {
  const registry = registryFor(useStoreApi());
  const cache = useRef({ key: "", rects: [] });
  const getSnapshot = () => {
    const rects = [];
    for (const [otherId, entry] of registry.entries) {
      if (otherId !== id && entry.rank < rank) rects.push(entry.rect);
    }
    const key = rects.map((r) => `${r.x},${r.y},${r.w},${r.h}`).join("|");
    if (key !== cache.current.key) cache.current = { key, rects };
    return cache.current.rects;
  };
  return useSyncExternalStore(registry.subscribe, getSnapshot);
}

/** 登記這條線的標籤範圍；rect 給 null（不常駐、線藏起來）就撤掉 */
export function usePublishLabelRect(id, rank, rect) {
  const registry = registryFor(useStoreApi());
  const x = rect?.x;
  const y = rect?.y;
  const w = rect?.w;
  const h = rect?.h;
  useLayoutEffect(() => {
    registry.publish(id, x === undefined ? null : { rank, rect: { x, y, w, h } });
  }, [registry, id, rank, x, y, w, h]);
  /* 線拿掉（篩選、收合群組）時撤掉登記，不然後面的標籤會繼續避開一塊空地 */
  useLayoutEffect(() => () => registry.publish(id, null), [registry, id]);
}
