// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import Disclosure from "./Disclosure";
import DisclosureToggle from "./DisclosureToggle";

vi.mock("../MIcon", () => ({ default: ({ name, className }) => <i data-icon={name} className={className} /> }));

let host;
let root;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("Disclosure", () => {
  const summary = () => host.querySelector("button[aria-expanded]");
  const body = () => document.getElementById(summary().getAttribute("aria-controls"));

  test("收合列是按鈕：標題、選填圖示與說明、箭頭；其餘屬性掛在外框上；預設收起且內容 inert", () => {
    act(() => root.render(
      <Disclosure label="進階設定" icon="tune" meta="選填" className="span" bodyClassName="grid" data-guide="advanced">
        <input aria-label="學期" />
      </Disclosure>,
    ));

    const frame = host.firstElementChild;
    expect(frame.getAttribute("data-guide")).toBe("advanced");
    expect(frame.className).toContain("span");
    expect(summary().type).toBe("button");
    expect(summary().getAttribute("aria-expanded")).toBe("false");
    expect(summary().textContent).toBe("進階設定選填");
    expect([...summary().querySelectorAll("[data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["tune", "expand_more"]);
    expect(body().hasAttribute("inert")).toBe(true);
    expect(body().querySelector(".grid input")).toBeTruthy();
  });

  test("點收合列切換展開：aria-expanded 與內容的 inert 跟著變", () => {
    act(() => root.render(<Disclosure label="進階設定"><input aria-label="學期" /></Disclosure>));

    act(() => summary().click());
    expect(summary().getAttribute("aria-expanded")).toBe("true");
    expect(body().hasAttribute("inert")).toBe(false);

    act(() => summary().click());
    expect(summary().getAttribute("aria-expanded")).toBe("false");
    expect(body().hasAttribute("inert")).toBe(true);
  });

  test("inline：外框多掛 inline 樣式、仍是同一個向下箭頭，內容不加 boxed 的上邊距", () => {
    act(() => root.render(<Disclosure variant="inline" label="執行證據" className="evidence"><pre>stderr</pre></Disclosure>));

    const frame = host.firstElementChild;
    expect(frame.className.split(" ")).toEqual(expect.arrayContaining(["evidence"]));
    expect(frame.className.split(" ").length).toBe(3);
    expect([...summary().querySelectorAll("[data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["expand_more"]);
    const pre = body().querySelector("pre");
    expect(pre.textContent).toBe("stderr");
    expect(pre.parentElement.className).toBe("");
  });

  test("沒給圖示與說明就不畫；defaultOpen 一開始就展開", () => {
    act(() => root.render(<Disclosure label="錯誤代碼" defaultOpen><p>401</p></Disclosure>));

    expect(summary().getAttribute("aria-expanded")).toBe("true");
    expect(body().hasAttribute("inert")).toBe(false);
    expect([...summary().querySelectorAll("[data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["expand_more"]);
    expect(summary().textContent).toBe("錯誤代碼");
  });
});

describe("DisclosureToggle", () => {
  test("按鈕版：展開狀態同步到 aria-expanded、點了呼叫 onToggle、文字後面一個向下箭頭", () => {
    const onToggle = vi.fn();
    const render = (open) => act(() => root.render(
      <DisclosureToggle open={open} onToggle={onToggle} className="placed" aria-controls="keys">
        顯示已失效的金鑰（2）
      </DisclosureToggle>,
    ));
    render(false);

    const button = host.querySelector("button");
    expect(button.type).toBe("button");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.getAttribute("aria-controls")).toBe("keys");
    expect(button.className.split(" ")).toEqual(expect.arrayContaining(["placed"]));
    expect(button.textContent).toBe("顯示已失效的金鑰（2）");
    expect([...button.querySelectorAll("[data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["expand_more"]);

    act(() => button.click());
    expect(onToggle).toHaveBeenCalledTimes(1);

    render(true);
    expect(host.querySelector("button").getAttribute("aria-expanded")).toBe("true");
  });
});
