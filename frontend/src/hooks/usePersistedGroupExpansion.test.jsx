// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test } from "vitest";
import usePersistedGroupExpansion, { loadCollapsedGroups, saveGroupCollapsed } from "./usePersistedGroupExpansion";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const KEY = "skylab:collapsed-groups:test";
let host;
let root;
let latest;

function Probe({ scope = "test", groupId, options }) {
  latest = usePersistedGroupExpansion(scope, groupId, options);
  return null;
}

beforeEach(() => {
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.body.innerHTML = "";
  window.localStorage.clear();
});

test("沒記過的群組預設展開", async () => {
  await act(async () => root.render(<Probe groupId="course-a" />));
  expect(latest[0]).toBe(true);
});

test("收起後寫進本機，再展開就從清單移除", async () => {
  await act(async () => root.render(<Probe groupId="course-a" />));
  await act(async () => latest[1]());
  expect(latest[0]).toBe(false);
  expect(JSON.parse(window.localStorage.getItem(KEY))).toEqual(["course-a"]);
  await act(async () => latest[1]());
  expect(latest[0]).toBe(true);
  expect(JSON.parse(window.localStorage.getItem(KEY))).toEqual([]);
});

test("重新掛載時沿用收起狀態；數字 id 也認得", async () => {
  window.localStorage.setItem(KEY, JSON.stringify(["42"]));
  await act(async () => root.render(<Probe groupId={42} />));
  expect(latest[0]).toBe(false);
});

test("defaultExpanded=false：預設收起，展開才記進本機，重新掛載沿用", async () => {
  const EXPANDED_KEY = "skylab:expanded-groups:test";
  /* 舊版留下的「收起」紀錄不影響預設收起的群組 */
  window.localStorage.setItem(KEY, JSON.stringify(["pending"]));
  await act(async () => root.render(<Probe groupId="pending" options={{ defaultExpanded: false }} />));
  expect(latest[0]).toBe(false);

  await act(async () => latest[1]());
  expect(latest[0]).toBe(true);
  expect(JSON.parse(window.localStorage.getItem(EXPANDED_KEY))).toEqual(["pending"]);

  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<Probe groupId="pending" options={{ defaultExpanded: false }} />));
  expect(latest[0]).toBe(true);

  await act(async () => latest[1]());
  expect(latest[0]).toBe(false);
  expect(JSON.parse(window.localStorage.getItem(EXPANDED_KEY))).toEqual([]);
});

test("各頁面（scope）各記各的", async () => {
  saveGroupCollapsed("other-page", "course-a", true);
  await act(async () => root.render(<Probe groupId="course-a" />));
  expect(latest[0]).toBe(true);
});

test("內容壞掉時當作沒有收起的群組", () => {
  window.localStorage.setItem(KEY, "{not json");
  expect(loadCollapsedGroups("test")).toEqual([]);
  window.localStorage.setItem(KEY, JSON.stringify({ a: 1 }));
  expect(loadCollapsedGroups("test")).toEqual([]);
});

test("只留最近收起的 200 筆", () => {
  for (let i = 0; i < 205; i += 1) saveGroupCollapsed("test", `g-${i}`, true);
  const ids = loadCollapsedGroups("test");
  expect(ids).toHaveLength(200);
  expect(ids[0]).toBe("g-5");
  expect(ids.at(-1)).toBe("g-204");
});

test("localStorage 丟例外時照預設展開", () => {
  const original = Object.getOwnPropertyDescriptor(window, "localStorage");
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    get() {
      throw new Error("blocked");
    },
  });
  try {
    expect(loadCollapsedGroups("test")).toEqual([]);
    expect(() => saveGroupCollapsed("test", "course-a", true)).not.toThrow();
  } finally {
    Object.defineProperty(window, "localStorage", original);
  }
});
