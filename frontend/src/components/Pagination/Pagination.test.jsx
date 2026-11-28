// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../../i18n";
import Pagination from "./Pagination";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host;
let root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.body.innerHTML = "";
});

async function render(props) {
  const onChange = vi.fn();
  await act(async () => {
    root.render(<Pagination info="共 794 筆" onChange={onChange} {...props} />);
  });
  return {
    onChange,
    prev: host.querySelector('button[aria-label="上一頁"]'),
    next: host.querySelector('button[aria-label="下一頁"]'),
    pageTexts: () => [...host.querySelectorAll("ol li")].map((item) => item.textContent),
    pageButton: (label) => [...host.querySelectorAll("ol button")].find((button) => button.textContent === label),
    jump: () => host.querySelector("input"),
  };
}

function typeInto(input, value) {
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  setValue.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function press(input, key) {
  input.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
}

test("左邊顯示傳入的資訊；上一頁／下一頁是箭頭鈕，文字放在無障礙名稱", async () => {
  const { prev, next } = await render({ page: 1, totalPages: 3 });
  expect(host.textContent).toContain("共 794 筆");
  expect(host.querySelector("nav").getAttribute("aria-label")).toBe("分頁");
  expect(prev.textContent).not.toContain("上一頁");
  expect(next).toBeTruthy();
});

test("第一頁停用上一頁、最後一頁停用下一頁", async () => {
  let view = await render({ page: 0, totalPages: 2 });
  expect(view.prev.disabled).toBe(true);
  expect(view.next.disabled).toBe(false);
  view = await render({ page: 1, totalPages: 2 });
  expect(view.prev.disabled).toBe(false);
  expect(view.next.disabled).toBe(true);
});

test("箭頭回報目標頁碼（從 0 起算）", async () => {
  const { prev, next, onChange } = await render({ page: 2, totalPages: 5 });
  await act(async () => prev.click());
  await act(async () => next.click());
  expect(onChange.mock.calls).toEqual([[1], [3]]);
});

test("7 頁內頁碼全部畫出來；目前頁標 aria-current", async () => {
  const view = await render({ page: 2, totalPages: 5 });
  expect(view.pageTexts()).toEqual(["1", "2", "3", "4", "5"]);
  expect(view.pageButton("3").getAttribute("aria-current")).toBe("page");
  expect(view.pageButton("3").getAttribute("aria-label")).toBe("第 3 頁");
  expect(view.pageButton("2").hasAttribute("aria-current")).toBe(false);
});

test("頁數多時固定 7 格：頭尾各一、目前頁前後各一，靠近頭尾改連續五格", async () => {
  let view = await render({ page: 0, totalPages: 16 });
  expect(view.pageTexts()).toEqual(["1", "2", "3", "4", "5", "…", "16"]);
  view = await render({ page: 3, totalPages: 16 });
  expect(view.pageTexts()).toEqual(["1", "2", "3", "4", "5", "…", "16"]);
  view = await render({ page: 4, totalPages: 16 });
  expect(view.pageTexts()).toEqual(["1", "…", "4", "5", "6", "…", "16"]);
  view = await render({ page: 11, totalPages: 16 });
  expect(view.pageTexts()).toEqual(["1", "…", "11", "12", "13", "…", "16"]);
  view = await render({ page: 12, totalPages: 16 });
  expect(view.pageTexts()).toEqual(["1", "…", "12", "13", "14", "15", "16"]);
  view = await render({ page: 15, totalPages: 16 });
  expect(view.pageTexts()).toEqual(["1", "…", "12", "13", "14", "15", "16"]);
});

test("點頁碼跳到那一頁；點目前頁不觸發", async () => {
  const view = await render({ page: 4, totalPages: 16 });
  await act(async () => view.pageButton("16").click());
  await act(async () => view.pageButton("5").click());
  expect(view.onChange.mock.calls).toEqual([[15]]);
});

test("前往欄：只收數字，Enter 跳頁、超出範圍夾到頭尾、跳完清空", async () => {
  const view = await render({ page: 4, totalPages: 16 });
  const input = view.jump();
  expect(input.getAttribute("aria-label")).toBe("前往頁數（共 16 頁）");
  /* Trans 把輸入框嵌在句子中間：前往 [__] 頁 */
  const label = input.closest("label");
  expect(label.textContent.replace(/\s+/g, " ")).toBe("前往 頁");
  expect(label.firstChild.textContent.trim()).toBe("前往");
  expect(label.lastChild.textContent.trim()).toBe("頁");

  await act(async () => typeInto(input, "9a"));
  expect(input.value).toBe("9");
  await act(async () => press(input, "Enter"));
  expect(input.value).toBe("");

  await act(async () => typeInto(input, "99"));
  await act(async () => press(input, "Enter"));
  await act(async () => typeInto(input, "0"));
  await act(async () => press(input, "Enter"));
  expect(view.onChange.mock.calls).toEqual([[8], [15], [0]]);
});

test("前往欄：離開欄位也會跳；Esc 清掉不跳；輸入目前頁不觸發", async () => {
  const view = await render({ page: 4, totalPages: 16 });
  const input = view.jump();

  await act(async () => typeInto(input, "3"));
  await act(async () => input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  await act(async () => typeInto(input, "7"));
  await act(async () => press(input, "Escape"));
  expect(input.value).toBe("");
  await act(async () => typeInto(input, "5"));
  await act(async () => press(input, "Enter"));
  expect(view.onChange.mock.calls).toEqual([[2]]);
});

test("頁數少（7 頁內）前往欄只在窄容器出現；只有一頁時只剩資訊", async () => {
  let view = await render({ page: 0, totalPages: 5 });
  expect(view.jump().closest("label").className).toMatch(/jumpNarrowOnly/);
  view = await render({ page: 0, totalPages: 8 });
  expect(view.jump().closest("label").className).not.toMatch(/jumpNarrowOnly/);

  await render({ page: 0, totalPages: 1 });
  expect(host.textContent).toBe("共 794 筆");
  expect(host.querySelector("nav")).toBeNull();
  expect(host.querySelector("input")).toBeNull();
});
