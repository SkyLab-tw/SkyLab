// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import StatusBadge from "./StatusBadge";

const render = (node) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(node);
  return host.firstElementChild;
};

test("帶 tone 色調類別、圖示在文字前面，圖示不進輔助技術", () => {
  const badge = render(<StatusBadge tone="pending" icon="person_search">等待老師確認</StatusBadge>);
  expect(badge.className).toMatch(/badge/);
  expect(badge.className).toMatch(/pending/);
  expect(badge.firstElementChild.textContent).toBe("person_search");
  expect(badge.firstElementChild.getAttribute("aria-hidden")).toBe("true");
  expect(badge.textContent).toBe("person_search等待老師確認");
});

test("沒有圖示就只有文字；不認得的 tone 退回中性灰", () => {
  const badge = render(<StatusBadge tone="weird">尚未檢查</StatusBadge>);
  expect(badge.children).toHaveLength(0);
  expect(badge.className).toMatch(/muted/);
  expect(badge.className).not.toMatch(/weird|undefined/);
});

test("className 只疊在後面放位置，其他屬性原樣傳下去", () => {
  const badge = render(<StatusBadge tone="success" className="slot" title="提示" data-guide="x">通過</StatusBadge>);
  expect(badge.className).toMatch(/success/);
  expect(badge.className.endsWith("slot")).toBe(true);
  expect(badge.getAttribute("title")).toBe("提示");
  expect(badge.getAttribute("data-guide")).toBe("x");
});
