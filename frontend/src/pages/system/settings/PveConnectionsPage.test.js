import { describe, expect, test } from "vitest";
import { parseNodePriority } from "./PveConnectionsPage";

describe("PveConnectionsPage 節點優先度", () => {
  test("1–10 的整數照原值送出", () => {
    expect(parseNodePriority("1")).toBe(1);
    expect(parseNodePriority("10")).toBe(10);
    expect(parseNodePriority(5)).toBe(5);
    expect(parseNodePriority(" 7 ")).toBe(7);
  });

  test("清空時擋下，不換成 0 或別的數字", () => {
    expect(parseNodePriority("")).toBeNull();
    expect(parseNodePriority("   ")).toBeNull();
    expect(parseNodePriority(null)).toBeNull();
    expect(parseNodePriority(undefined)).toBeNull();
  });

  test("超出後端的 1–10 範圍或不是整數時擋下", () => {
    expect(parseNodePriority("0")).toBeNull();
    expect(parseNodePriority("11")).toBeNull();
    expect(parseNodePriority("-1")).toBeNull();
    expect(parseNodePriority("2.5")).toBeNull();
    expect(parseNodePriority("abc")).toBeNull();
  });
});
