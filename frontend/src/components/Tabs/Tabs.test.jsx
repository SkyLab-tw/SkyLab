// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import Tabs from "./Tabs";

vi.mock("../MIcon", () => ({ default: ({ name }) => <i data-icon={name} /> }));

const OPTIONS = [
  { value: "models", label: "模型", icon: "model_training", badge: 3, buttonProps: { "data-guide-tab": "models" } },
  { value: "proxy", label: "金鑰 API 呼叫", badge: 0 },
  { value: "users", label: "使用者用量" },
];

let host;
let root;
let changes;

function Harness({ initial = "models", options = OPTIONS }) {
  const [value, setValue] = useState(initial);
  return <Tabs options={options} value={value} onChange={(next) => { changes.push(next); setValue(next); }} ariaLabel="明細" />;
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  changes = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const tabs = () => [...host.querySelectorAll('[role="tab"]')];
const press = (key) => act(() => {
  host.querySelector('[role="tablist"]').dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
});

describe("Tabs", () => {
  test("tablist／tab 角色、選中的 aria-selected，只有選中的分頁在 Tab 鍵順序裡", () => {
    act(() => root.render(<Harness />));

    const list = host.querySelector('[role="tablist"]');
    expect(list.getAttribute("aria-label")).toBe("明細");
    expect(tabs().map((tab) => tab.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
    expect(tabs().map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    expect(tabs()[0].getAttribute("data-guide-tab")).toBe("models");
  });

  test("徽章：0 也顯示，沒給就不畫", () => {
    act(() => root.render(<Harness />));

    expect(tabs()[0].textContent).toBe("模型3");
    expect(tabs()[1].textContent).toBe("金鑰 API 呼叫0");
    expect(tabs()[2].textContent).toBe("使用者用量");
  });

  test("點分頁切換", () => {
    act(() => root.render(<Harness />));
    act(() => tabs()[2].click());

    expect(changes).toEqual(["users"]);
    expect(tabs()[2].getAttribute("aria-selected")).toBe("true");
  });

  test("左右鍵頭尾相接、Home／End，切換並把焦點移過去", () => {
    act(() => root.render(<Harness />));
    tabs()[0].focus();

    press("ArrowLeft");
    expect(changes.at(-1)).toBe("users");
    expect(document.activeElement).toBe(tabs()[2]);

    press("ArrowRight");
    expect(changes.at(-1)).toBe("models");

    press("End");
    expect(changes.at(-1)).toBe("users");
    press("Home");
    expect(changes.at(-1)).toBe("models");
    expect(document.activeElement).toBe(tabs()[0]);
  });

  test("value 對不到任何分頁時，第一個分頁留在 Tab 鍵順序裡", () => {
    act(() => root.render(<Harness initial="missing" />));

    expect(tabs().map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    expect(tabs().every((tab) => tab.getAttribute("aria-selected") === "false")).toBe(true);
  });

  test("字串標籤帶 data-label（CSS 依粗體預留寬度用），文字只出現一次；非字串標籤不帶", () => {
    const options = [...OPTIONS.slice(0, 2), { value: "node", label: <em>節點</em> }];
    act(() => root.render(<Harness options={options} />));

    const labels = tabs().map((tab) => tab.querySelector("[data-label]"));
    expect(labels[0].getAttribute("data-label")).toBe("模型");
    expect(labels[1].getAttribute("data-label")).toBe("金鑰 API 呼叫");
    expect(labels[2]).toBeNull();
    expect(tabs()[2].textContent).toBe("節點");
  });

  test("只有一種樣子：圖示一律包進圓角方塊；沒給圖示就不畫方塊", () => {
    act(() => root.render(<Harness />));

    const box = tabs()[0].querySelector('[class*="iconBox"]');
    expect(box?.querySelector('[data-icon="model_training"]')).not.toBeNull();
    expect(tabs()[0].getAttribute("aria-selected")).toBe("true");
    expect(tabs()[0].textContent).toBe("模型3");
    expect(tabs()[1].querySelector('[class*="iconBox"]')).toBeNull();
  });
});
