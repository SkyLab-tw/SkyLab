import { describe, expect, test } from "vitest";
import { FLOW_ANCHORS, flowAnchor } from "./flowAnchors";

/* 跟 pageGuides.test.js 同一套做法：把頁面原始碼整批讀進來，找出實際存在的錨點 */
const sources = import.meta.glob(["../../**/*.jsx", "!../../**/*.test.jsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const ANCHOR_PATTERNS = [
  /data-(page-)?guide="([^"]+)"/g,
  /["']data-(page-)?guide["']\s*:\s*["']([^"']+)["']/g,
];

const definedAnchors = new Set(Object.values(sources).flatMap((text) =>
  ANCHOR_PATTERNS.flatMap((pattern) =>
    [...text.matchAll(pattern)].map((match) => `${match[1] ? "page-guide" : "guide"}:${match[2]}`))));

describe("流程步驟的錨點對照", () => {
  test("每個 selector 都指向頁面原始碼裡還在的錨點", () => {
    const missing = Object.entries(FLOW_ANCHORS).flatMap(([flowId, steps]) =>
      Object.entries(steps).flatMap(([index, selector]) =>
        [...selector.matchAll(/\[data-(page-)?guide="([^"]+)"\]/g)]
          .map((match) => `${match[1] ? "page-guide" : "guide"}:${match[2]}`)
          .filter((anchor) => !definedAnchors.has(anchor))
          .map((anchor) => `${flowId}[${index}] → ${anchor}`)));
    expect(missing).toEqual([]);
  });

  test("每個 selector 都是 data-guide／data-page-guide 錨點，不靠 class 或標籤", () => {
    for (const steps of Object.values(FLOW_ANCHORS)) {
      for (const selector of Object.values(steps)) {
        expect(selector).toMatch(/^\[data-(page-)?guide="[a-z0-9-]+"\]$/);
      }
    }
  });

  test("沒登錄的流程或步驟回 null，呼叫端就只換頁不打光", () => {
    expect(flowAnchor("publish_service", 1)).toBe('[data-guide="firewall-create"]');
    expect(flowAnchor("request_machine", 1)).toBeNull();
    expect(flowAnchor("unknown_flow", 0)).toBeNull();
  });
});
