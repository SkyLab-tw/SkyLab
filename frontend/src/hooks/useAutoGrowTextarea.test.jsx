// @vitest-environment happy-dom
import { act, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import useAutoGrowTextarea from "./useAutoGrowTextarea";

/* happy-dom 不排版：內容高度、含框寬度、有沒有版面（offsetParent）都由測試指定。
   內容高度可以依當下的 overflow-y 回傳不同值，模擬「冒出捲軸、字被擠到下一行」 */
const MAX = 168;
let host;
let root;
let measure;
let outerWidth;
let visible;
let measureCalls;
let resizeCallback;
let setText;
let setActive;
const originalResizeObserver = globalThis.ResizeObserver;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  measure = () => 36;
  outerWidth = 300;
  visible = true;
  measureCalls = 0;
  resizeCallback = null;
  globalThis.ResizeObserver = class {
    constructor(callback) { resizeCallback = callback; }
    observe() {}
    disconnect() {}
  };
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get() { measureCalls += 1; return measure(this); },
  });
  Object.defineProperty(HTMLTextAreaElement.prototype, "offsetWidth", {
    configurable: true,
    get() { return outerWidth; },
  });
  Object.defineProperty(HTMLTextAreaElement.prototype, "offsetParent", {
    configurable: true,
    get() { return visible ? document.body : null; },
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete HTMLTextAreaElement.prototype.scrollHeight;
  delete HTMLTextAreaElement.prototype.offsetWidth;
  delete HTMLTextAreaElement.prototype.offsetParent;
  globalThis.ResizeObserver = originalResizeObserver;
});

function Harness({ initialActive = true }) {
  const ref = useRef(null);
  const [text, updateText] = useState("");
  const [active, updateActive] = useState(initialActive);
  setText = updateText;
  setActive = updateActive;
  useAutoGrowTextarea(ref, text, active);
  return <textarea ref={ref} rows={1} value={text} readOnly style={{ maxHeight: `${MAX}px` }} />;
}

function mount(props) {
  act(() => root.render(<Harness {...props} />));
  return host.querySelector("textarea");
}

describe("useAutoGrowTextarea", () => {
  test("沒到上限時跟著內容長高，而且不開捲軸", () => {
    const textarea = mount();
    expect(textarea.style.height).toBe("36px");
    expect(textarea.style.overflowY).toBe("hidden");

    measure = () => 57;
    act(() => setText("第一行\n第二行"));
    expect(textarea.style.height).toBe("57px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  test("超過 max-height 才開捲軸，內容變少又收回", () => {
    const textarea = mount();
    measure = () => 260;
    act(() => setText("很多行"));
    expect(textarea.style.overflowY).toBe("auto");

    measure = () => 36;
    act(() => setText("一行"));
    expect(textarea.style.height).toBe("36px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  /* 縮放 90% 時，一行字的框會冒出捲軸、字被擠成兩行；量的時候一定要先關掉捲軸，
     不然會量到兩行，寬度一變又量回一行，輸入框在一行和兩行之間不停跳 */
  test("量高度前先關掉捲軸，結果不受上一次的捲軸狀態影響", () => {
    measure = (el) => (el.style.overflowY === "hidden" ? 36 : 57);
    const textarea = mount();
    textarea.style.overflowY = "auto";
    act(() => setText("我想檢查/root/test/test.txt 是否存在 有在的話給對"));
    expect(textarea.style.height).toBe("36px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  test("自己的捲軸出現或消失不算寬度改變；含框寬度變了才重新量", () => {
    mount();
    const before = measureCalls;
    act(() => resizeCallback([]));
    expect(measureCalls).toBe(before);

    outerWidth = 420;
    act(() => resizeCallback([]));
    expect(measureCalls).toBe(before + 1);
  });

  /* AI 助手面板打開時寬度從 0 展開：量高度那一刻還很窄、量得很高；
     之後 ResizeObserver 第一次回報時寬度已經變了，要拿「量的當下」的寬度來比，才會重量 */
  test("量完之後寬度才變（展開動畫中先量了），第一次回報就重新量", () => {
    outerWidth = 40;
    measure = () => (outerWidth < 100 ? 264 : 36);
    const textarea = mount();
    expect(textarea.style.height).toBe("264px");

    outerWidth = 380;
    act(() => resizeCallback([]));
    expect(textarea.style.height).toBe("36px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  test("看不見或還沒啟用時不量，啟用後才量", () => {
    visible = false;
    const textarea = mount({ initialActive: false });
    expect(textarea.style.height).toBe("");

    visible = true;
    act(() => setActive(true));
    expect(textarea.style.height).toBe("36px");
  });
});
