// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import Tabs from "./Tabs";

vi.mock("../MIcon", () => ({ default: ({ name }) => <i data-icon={name} /> }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key) => (key === "Tabs.more" ? "更多" : key) }) }));

/* happy-dom 不排版：每個分頁寬 100、「更多」寬 80，整組需要的寬度照實際排出來的分頁算；
   可用寬度可調，ResizeObserver 換成手動觸發，模擬視窗變寬、變窄 */
const TAB_WIDTH = 100;
const MORE_WIDTH = 80;
const OPTIONS = [
  { value: "overview", label: "班級總覽", icon: "dashboard" },
  { value: "students", label: "加入學生", icon: "groups", badge: 32 },
  { value: "machines", label: "上課環境", icon: "account_tree" },
  { value: "weekly", label: "每週內容", icon: "calendar_view_week" },
  { value: "progress", label: "課堂監看", icon: "cast_for_education" },
  { value: "ai", label: "AI 導師檢查", icon: "auto_awesome" },
];

let host;
let root;
let available;
let resizeCallback;
let observed;
let changes;
const originalResizeObserver = globalThis.ResizeObserver;
const originalRect = HTMLElement.prototype.getBoundingClientRect;

const isRoot = (el) => el.firstElementChild?.getAttribute?.("role") === "tablist";
const rect = (width) => ({ width, height: 44, top: 0, left: 0, right: width, bottom: 44, x: 0, y: 0 });

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  available = 450;
  observed = [];
  changes = [];
  globalThis.ResizeObserver = class {
    constructor(callback) { resizeCallback = callback; }
    observe(target) { observed.push(target); }
    disconnect() {}
  };
  HTMLElement.prototype.getBoundingClientRect = function getRect() {
    if (this.getAttribute("role") === "tab") return rect(TAB_WIDTH);
    if (this.getAttribute("aria-haspopup") === "listbox" || this.getAttribute("aria-hidden") === "true") return rect(MORE_WIDTH);
    return originalRect.call(this);
  };
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
    configurable: true,
    get() {
      if (!isRoot(this)) return 0;
      const tabCount = this.firstElementChild.querySelectorAll('[role="tab"]').length;
      const hasMore = Boolean(this.querySelector('[aria-haspopup="listbox"]'));
      return tabCount * TAB_WIDTH + (hasMore ? MORE_WIDTH : 0);
    },
  });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return isRoot(this) ? available : 0; },
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete HTMLElement.prototype.scrollWidth;
  delete HTMLElement.prototype.clientWidth;
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  globalThis.ResizeObserver = originalResizeObserver;
});

function Harness({ initial }) {
  const [value, setValue] = useState(initial);
  return <Tabs options={OPTIONS} value={value} onChange={(next) => { changes.push(next); setValue(next); }} ariaLabel="班級" />;
}

const render = (initial = "students") => act(() => root.render(<Harness initial={initial} />));
const resize = (width) => act(() => {
  resizeCallback(observed.map((target) => ({ target, contentRect: { width, height: 44 } })));
});
const tabValues = () => [...host.querySelectorAll('[role="tab"]')].map((tab) => tab.dataset.tabsValue);
const moreButton = () => host.querySelector('[aria-haspopup="listbox"]');

describe("Tabs 放不下時收進「更多」", () => {
  test("放得下就全部排開，沒有「更多」", () => {
    available = 800;
    render();

    expect(tabValues()).toEqual(OPTIONS.map((option) => option.value));
    expect(moreButton()).toBeNull();
  });

  test("放不下：排得下的照排（都帶字），其餘收進「更多」", () => {
    render();

    expect(tabValues()).toEqual(["overview", "students", "machines"]);
    expect(moreButton().textContent).toContain("更多");
    expect(host.querySelector('[role="tablist"]').contains(moreButton())).toBe(false);
  });

  test("選中的分頁一定排在外面：選到收起來的那個，它換到外面最後一格", () => {
    render("ai");

    expect(tabValues()).toEqual(["overview", "students", "ai"]);
    expect(host.querySelector('[aria-selected="true"]').dataset.tabsValue).toBe("ai");
  });

  test("點「更多」列出收起來的分頁，選了就切換", () => {
    render();
    act(() => moreButton().click());

    const listbox = document.querySelector('[role="listbox"]');
    const options = [...listbox.querySelectorAll('[role="option"]')];
    expect(options.map((option) => option.textContent)).toEqual(["每週內容", "課堂監看", "AI 導師檢查"]);

    act(() => options[1].click());
    expect(changes).toEqual(["progress"]);
    expect(tabValues()).toEqual(["overview", "students", "progress"]);
  });

  test("外層變寬一路排回來，全部放得下「更多」就消失；變窄再收", () => {
    render();
    expect(moreButton()).not.toBeNull();

    available = 800;
    resize(900);
    expect(tabValues()).toHaveLength(OPTIONS.length);
    expect(moreButton()).toBeNull();

    available = 450;
    resize(470);
    expect(tabValues()).toEqual(["overview", "students", "machines"]);
  });
});
