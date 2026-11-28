// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import SegmentedControl from "./SegmentedControl";

vi.mock("../MIcon", () => ({ default: ({ name }) => <i data-icon={name} /> }));

/* happy-dom 不排版：把分段組「全部展開需要的寬度」與「實際可用寬度」接成可調的數字，
   ResizeObserver 換成手動觸發，模擬視窗變寬、變窄 */
const OPTIONS = [
  { value: "all", label: "全部類型" },
  { value: "vm", label: "VM 申請", badge: 3 },
  { value: "spec", label: "規格變更" },
  { value: "restore", label: "還原備份", buttonProps: { disabled: true } },
];
const NATURAL_WIDTH = 650;

let host;
let root;
let available;
let resizeCallback;
let observed;
const originalResizeObserver = globalThis.ResizeObserver;

const isExpandedGroup = (el) => el.getAttribute?.("role") === "group" && !/segmentCollapsed/.test(el.className);

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  available = 600;
  observed = [];
  globalThis.ResizeObserver = class {
    constructor(callback) { resizeCallback = callback; }
    observe(target) { observed.push(target); }
    disconnect() {}
  };
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
    configurable: true,
    get() { return isExpandedGroup(this) ? NATURAL_WIDTH : 0; },
  });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return this.getAttribute?.("role") === "group" ? available : 0; },
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
  globalThis.ResizeObserver = originalResizeObserver;
});

/** 觸發一次尺寸通知：觀察中的每個元素回報同一個寬高 */
const resize = (width, height = 40) => act(() => {
  resizeCallback(observed.map((target) => ({ target, contentRect: { width, height } })));
});
const trigger = () => host.querySelector('[aria-haspopup="listbox"]');
const segments = () => [...host.querySelectorAll("[aria-pressed]")];

function render(onChange = () => {}, value = "all") {
  act(() => root.render(<SegmentedControl options={OPTIONS} value={value} onChange={onChange} ariaLabel="類型" />));
}

describe("SegmentedControl 放不下時收成下拉", () => {
  test("放得下就是分段，不出現下拉鈕", () => {
    available = 800;
    render();

    expect(trigger()).toBeNull();
    expect(segments()).toHaveLength(4);
  });

  test("放不下收成下拉；外層變寬再展開，變窄又收回", () => {
    render();
    expect(trigger()).not.toBeNull();
    expect(trigger().textContent).toContain("全部類型");
    expect(segments()).toHaveLength(0);
    expect(host.querySelector('[role="group"]').getAttribute("aria-label")).toBe("類型");

    available = 700;
    resize(900);
    expect(trigger()).toBeNull();
    expect(segments()).toHaveLength(4);

    available = 600;
    resize(620);
    expect(trigger()).not.toBeNull();
  });

  test("下拉清單：列出全部選項、停用的不能選，選了回傳 value", () => {
    const onChange = vi.fn();
    render(onChange);
    act(() => trigger().click());

    const listbox = document.querySelector('[role="listbox"]');
    expect(listbox.getAttribute("aria-label")).toBe("類型");
    const options = [...listbox.querySelectorAll('[role="option"]')];
    expect(options.map((option) => option.getAttribute("aria-selected"))).toEqual(["true", "false", "false", "false"]);
    expect(options[3].disabled).toBe(true);

    act(() => options[1].click());
    expect(onChange).toHaveBeenCalledWith("vm");
  });

  test("清單開著時只有高度變化不會重量、不會把清單關掉", () => {
    render();
    resize(620, 40);
    act(() => trigger().click());
    expect(document.querySelector('[role="listbox"]')).not.toBeNull();

    resize(620, 900);
    expect(document.querySelector('[role="listbox"]')).not.toBeNull();
    expect(trigger().getAttribute("aria-expanded")).toBe("true");
  });
});
