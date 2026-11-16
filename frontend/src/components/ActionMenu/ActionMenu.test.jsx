// @vitest-environment happy-dom
import { act, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ActionMenu from "./ActionMenu";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

function Harness({ onExtend = () => {}, onArchive = () => {}, onClose: onCloseSpy }) {
  const anchorRef = useRef(null);
  const [open, setOpen] = useState(true);
  const close = () => { onCloseSpy?.(); setOpen(false); };
  return (
    <>
      <button type="button" ref={anchorRef} data-test="anchor">⋮</button>
      <button type="button" data-test="outside">外面</button>
      {open && (
        <ActionMenu
          id="class-menu"
          anchorRef={anchorRef}
          ariaLabel="更多班級操作"
          onClose={close}
          items={[
            { key: "schedule", label: "編輯班級與課表", icon: "edit_calendar", onSelect: () => {}, disabled: true },
            { key: "extend", label: "延長課程日期", icon: "event_repeat", onSelect: onExtend },
            { key: "archive", label: "封存並回收", icon: "archive", onSelect: onArchive, danger: true, separatorBefore: true },
          ]}
        />
      )}
    </>
  );
}

const menu = () => document.querySelector('[role="menu"]');
const items = () => [...document.querySelectorAll('[role="menuitem"]')];
const anchor = () => document.querySelector('[data-test="anchor"]');
const press = (key) => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  act(() => { document.activeElement.dispatchEvent(event); });
  return event;
};

test("portal 到 body，焦點落在第一個可用的選項；危險項前面有分隔線", () => {
  act(() => { root.render(<Harness />); });
  expect(menu().parentElement).toBe(document.body);
  expect(menu().getAttribute("aria-label")).toBe("更多班級操作");
  expect(document.activeElement).toBe(items()[1]);
  expect(items()[2].previousElementSibling.getAttribute("role")).toBe("separator");
});

test("上下鍵跳過停用項、頭尾相接；Home／End 到頭尾", () => {
  act(() => { root.render(<Harness />); });
  press("ArrowDown");
  expect(document.activeElement.textContent).toContain("封存並回收");
  press("ArrowDown");
  expect(document.activeElement.textContent).toContain("延長課程日期");
  press("ArrowUp");
  expect(document.activeElement.textContent).toContain("封存並回收");
  press("Home");
  expect(document.activeElement.textContent).toContain("延長課程日期");
  press("End");
  expect(document.activeElement.textContent).toContain("封存並回收");
});

test("選了選項：先關選單、焦點回觸發鈕，再執行動作", () => {
  const onExtend = vi.fn();
  const onClose = vi.fn();
  act(() => { root.render(<Harness onExtend={onExtend} onClose={onClose} />); });
  act(() => { items()[1].click(); });
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onExtend).toHaveBeenCalledTimes(1);
  expect(menu()).toBeNull();
  expect(document.activeElement).toBe(anchor());
});

test("Esc 關閉、焦點回觸發鈕，並標成已處理（同頁其他聽 Esc 的元件不會跟著動作）", () => {
  const onClose = vi.fn();
  act(() => { root.render(<Harness onClose={onClose} />); });
  const event = press("Escape");
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(event.defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(anchor());
});

test("Tab 關閉並把焦點交回觸發鈕；點外面也關閉，點觸發鈕本身不算外面", () => {
  const onClose = vi.fn();
  act(() => { root.render(<Harness onClose={onClose} />); });
  act(() => { anchor().dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
  expect(onClose).not.toHaveBeenCalled();
  const tab = press("Tab");
  expect(tab.defaultPrevented).toBe(false);
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(anchor());
});
