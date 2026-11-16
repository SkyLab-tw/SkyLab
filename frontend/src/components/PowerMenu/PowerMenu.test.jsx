// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key) => key }) }));

import PowerMenu from "./PowerMenu";

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

function findButton(label) {
  return [...document.querySelectorAll("button")].find((b) => b.textContent.includes(label));
}

async function renderMenu(props) {
  const anchor = document.createElement("button");
  document.body.appendChild(anchor);
  await act(async () =>
    root.render(
      <PowerMenu
        resource={{ status: "running" }}
        onControl={() => {}}
        anchorRef={{ current: anchor }}
        {...props}
      />,
    ),
  );
}

test("power actions close the menu before running the action", async () => {
  const onClose = vi.fn();
  const onControl = vi.fn();
  await renderMenu({ onClose, onControl });
  await act(async () => findButton("PowerMenu.reboot").click());
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onControl).toHaveBeenCalledWith("reboot");
});

test("convert-to-template and delete leave closing to the caller (no double close)", async () => {
  const onClose = vi.fn();
  const onConvertTemplate = vi.fn();
  const onDeleteClick = vi.fn();
  await renderMenu({ onClose, onConvertTemplate, onDeleteClick });

  await act(async () => findButton("PowerMenu.convertTemplate").click());
  expect(onConvertTemplate).toHaveBeenCalledTimes(1);

  await act(async () => findButton("PowerMenu.delete").click());
  expect(onDeleteClick).toHaveBeenCalledTimes(1);

  expect(onClose).not.toHaveBeenCalled();
});

test("extra actions are hidden without their callbacks", async () => {
  await renderMenu({ onClose: () => {} });
  expect(findButton("PowerMenu.convertTemplate")).toBeUndefined();
  expect(findButton("PowerMenu.delete")).toBeUndefined();
});

test("鍵盤：焦點落在第一個可用動作，上下鍵頭尾相接，Esc 把焦點交回觸發鈕、Tab 關閉", async () => {
  const onClose = vi.fn();
  await renderMenu({ onClose });
  // renderMenu 把觸發鈕直接掛在 body 底下
  const anchor = [...document.body.children].find((el) => el.tagName === "BUTTON");
  const press = (key) => act(async () => {
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });

  expect(document.querySelector('[role="menu"]').getAttribute("aria-label")).toBe("PowerMenu.title");
  // 機器開著時「開機」停用，第一個可用的是「強制關機」
  expect(document.activeElement.textContent).toContain("PowerMenu.stop");
  await press("ArrowUp");
  expect(document.activeElement.textContent).toContain("PowerMenu.reboot");
  await press("ArrowDown");
  expect(document.activeElement.textContent).toContain("PowerMenu.stop");

  await press("Tab");
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(anchor);
});
