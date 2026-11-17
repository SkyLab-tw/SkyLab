// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import Disclosure from "./Disclosure";

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
  test("原生 details／summary：標題、選填圖示與說明、箭頭；其餘屬性掛在 details 上", () => {
    act(() => root.render(
      <Disclosure label="進階設定" icon="tune" meta="選填" className="span" bodyClassName="grid" data-guide="advanced">
        <input aria-label="學期" />
      </Disclosure>,
    ));

    const details = host.querySelector("details");
    expect(details.getAttribute("data-guide")).toBe("advanced");
    expect(details.className).toContain("span");
    expect(details.open).toBe(false);
    const summary = details.querySelector("summary");
    expect(summary.textContent).toBe("進階設定選填");
    expect([...summary.querySelectorAll("[data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["tune", "expand_more"]);
    expect(details.querySelector(".grid input")).toBeTruthy();
  });

  test("inline：外框多掛 inline 樣式、仍是同一個向下箭頭，內容在 body 裡", () => {
    act(() => root.render(<Disclosure variant="inline" label="執行證據" className="evidence"><pre>stderr</pre></Disclosure>));

    const details = host.querySelector("details");
    expect(details.className.split(" ")).toEqual(expect.arrayContaining(["evidence"]));
    expect(details.className.split(" ").length).toBe(3);
    expect([...details.querySelectorAll("summary [data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["expand_more"]);
    expect(details.querySelector("summary + div pre").textContent).toBe("stderr");
  });

  test("沒給圖示與說明就不畫；defaultOpen 一開始就展開", () => {
    act(() => root.render(<Disclosure label="錯誤代碼" defaultOpen><p>401</p></Disclosure>));

    const details = host.querySelector("details");
    expect(details.open).toBe(true);
    expect([...details.querySelectorAll("summary [data-icon]")].map((icon) => icon.dataset.icon)).toEqual(["expand_more"]);
    expect(details.querySelector("summary").textContent).toBe("錯誤代碼");
  });
});
