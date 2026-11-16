// @vitest-environment happy-dom
import { act, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ListboxPopover from "./ListboxPopover";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const OPTIONS = [
  { value: "w1", label: "第 1 週", description: "已建立檢查" },
  { value: "w2", label: "第 2 週", description: "尚未建立檢查" },
  { value: "w3", label: "第 3 週", disabled: true },
  { value: "w4", label: "第 4 週" },
];

let host;
let root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function Harness({ onSelect, onClose: onCloseSpy, value = "w2" }) {
  const anchorRef = useRef(null);
  const [open, setOpen] = useState(true);
  const close = () => { onCloseSpy?.(); setOpen(false); };
  return (
    <>
      <button type="button" ref={anchorRef} data-test="anchor">換週</button>
      <button type="button" data-test="outside">外面</button>
      {open && (
        <ListboxPopover
          id="weeks"
          anchorRef={anchorRef}
          ariaLabel="選擇週次"
          options={OPTIONS}
          value={value}
          onSelect={onSelect ?? (() => {})}
          onClose={close}
        />
      )}
    </>
  );
}

const listbox = () => document.querySelector('[role="listbox"]');
const options = () => [...document.querySelectorAll('[role="option"]')];
const press = (key) => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  act(() => { document.activeElement.dispatchEvent(event); });
  return event;
};

test("portal 到 body、標出目前選中的那項，並把焦點放在它上面", () => {
  act(() => { root.render(<Harness />); });
  expect(listbox().parentElement).toBe(document.body);
  expect(listbox().getAttribute("aria-label")).toBe("選擇週次");
  expect(options().map((el) => el.getAttribute("aria-selected"))).toEqual(["false", "true", "false", "false"]);
  expect(document.activeElement).toBe(options()[1]);
  expect(options()[0].textContent).toContain("已建立檢查");
});

test("上下鍵跳過停用的選項，Home／End 到頭尾，到底不繞回", () => {
  act(() => { root.render(<Harness />); });
  press("ArrowDown");
  expect(document.activeElement.textContent).toContain("第 4 週");
  press("ArrowDown");
  expect(document.activeElement.textContent).toContain("第 4 週");
  press("Home");
  expect(document.activeElement.textContent).toContain("第 1 週");
  press("ArrowUp");
  expect(document.activeElement.textContent).toContain("第 1 週");
  press("End");
  expect(document.activeElement.textContent).toContain("第 4 週");
});

test("點選項：先關清單、焦點回到觸發鈕，再回報選了哪個", () => {
  const onSelect = vi.fn();
  const onClose = vi.fn();
  act(() => { root.render(<Harness onSelect={onSelect} onClose={onClose} />); });
  act(() => { options()[3].click(); });
  expect(onSelect).toHaveBeenCalledWith("w4");
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(listbox()).toBeNull();
  expect(document.activeElement).toBe(document.querySelector('[data-test="anchor"]'));
});

test("Esc 關閉並把焦點交回觸發鈕，也標成已處理讓外層不重複動作", () => {
  const onClose = vi.fn();
  act(() => { root.render(<Harness onClose={onClose} />); });
  const event = press("Escape");
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(event.defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(document.querySelector('[data-test="anchor"]'));
});

test("Tab 關閉並把焦點交回觸發鈕，不攔預設行為", () => {
  const onClose = vi.fn();
  act(() => { root.render(<Harness onClose={onClose} />); });
  const event = press("Tab");
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(event.defaultPrevented).toBe(false);
  expect(document.activeElement).toBe(document.querySelector('[data-test="anchor"]'));
});

test("點清單外面就關閉，點觸發鈕本身不算外面（交給觸發鈕自己切換）", () => {
  const onClose = vi.fn();
  act(() => { root.render(<Harness onClose={onClose} />); });
  act(() => { document.querySelector('[data-test="anchor"]').dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
  expect(onClose).not.toHaveBeenCalled();
  act(() => { document.querySelector('[data-test="outside"]').dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
  expect(onClose).toHaveBeenCalledTimes(1);
});
