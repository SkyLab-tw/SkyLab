// @vitest-environment happy-dom

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { RubricTable, describeCheckStep } from "./AiJudgePanel";
import i18n from "../../../i18n";

const tr = (key, options) => i18n.t(`AiJudgePanel.${key}`, { ns: "teaching", ...options });

let cleanup = null;
afterEach(async () => {
  await cleanup?.();
  cleanup = null;
});

const ITEM = {
  id: "item-1",
  title: "PHP-FPM 服務執行中",
  detection_method: "在 Web 節點以 systemctl 確認 php8.2-fpm 狀態為 active。",
  detectable: "auto",
  judgement_mode: "ai",
  target_node_key: "web",
  check_steps: [{
    template_key: "web",
    command_key: "service",
    collector: { type: "command", argv: ["systemctl", "is-active", "php8.2-fpm"], timeout_seconds: 10 },
    assertion: { type: "text_equals", expected: "active" },
  }],
};
const MACHINE_NODES = [{ node_key: "web", name: "Nginx Web", sort_order: 1, role: "環境機器", resource_type: "lxc" }];

async function mountTable(items, { onDelete = () => {} } = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  cleanup = async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  };
  await act(async () => {
    root.render(
      <RubricTable items={items} onChange={() => {}} onDelete={onDelete} disabled={false} machineNodes={MACHINE_NODES} />,
    );
  });
  return container;
}

const clickOn = async (element) => {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
};

test("整列可點來展開／收合；點標題（編輯）、刪除鈕或正在選字時不切換", async () => {
  const onDelete = vi.fn();
  const container = await mountTable([ITEM], { onDelete });
  const detail = () => container.querySelector("#rubric-detail-0");
  const toggle = container.querySelector('[aria-controls="rubric-detail-0"]');

  // 點檢測方式的文字：展開，展開鈕也同步成已展開
  await clickOn(container.querySelector('[class*="rubricMethodText"]'));
  expect(detail()).toBeTruthy();
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  // 點狀態徽章：收合
  await clickOn(container.querySelector('[class*="detBadge"]'));
  expect(detail()).toBeNull();

  // 標題欄是編輯區
  await clickOn(container.querySelector("textarea"));
  expect(detail()).toBeNull();
  // 刪除鈕只做刪除
  await clickOn(container.querySelector('[class*="rubricDeleteBtn"]'));
  expect(onDelete).toHaveBeenCalledTimes(1);
  expect(detail()).toBeNull();
  // 展開鈕本身只切換一次（不會被整列的點擊再切回去）
  await clickOn(toggle);
  expect(detail()).toBeTruthy();

  // 正在反白選字（例如複製指令）時不切換
  vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => "systemctl" });
  await clickOn(container.querySelector('[class*="rubricMethodText"]'));
  expect(detail()).toBeTruthy();
});

test("把檢查步驟講成白話：做什麼、整行指令、通過條件與時限", () => {
  expect(describeCheckStep(ITEM.check_steps[0])).toEqual({
    icon: "terminal",
    label: tr("stepRunCommand"),
    target: "systemctl is-active php8.2-fpm",
    notes: [
      tr("stepPass", { value: tr("assertTextEquals", { value: tr("quotedValue", { value: "active" }) }) }),
      tr("stepTimeout", { count: 10 }),
    ],
  });
});

test("讀檔只讀前幾行時寫出來；沒有 collector 的舊格式沿用範本與指令名稱", () => {
  expect(describeCheckStep({
    collector: { type: "file_text", path: "/etc/nginx/nginx.conf", read_mode: "head", lines: 20 },
  })).toMatchObject({ label: tr("stepReadFile"), target: "/etc/nginx/nginx.conf", notes: [tr("stepReadHead", { count: 20 })] });
  const legacy = describeCheckStep({ template_key: "", command_key: "check_port", command_label: "連接埠", parameters: {} });
  expect(legacy).toMatchObject({ icon: "rule", target: "", notes: [] });
  expect(legacy.label).toMatch(/\/ 連接埠$/);
});

test("展開後在檢測方式底下列出機器與步驟：摘要晶片收起、判定方式不跟徽章重複、不露出系統代號", async () => {
  const container = await mountTable([ITEM]);
  const methodCell = container.querySelector('[class*="rubricDescriptionCell"]');
  expect(container.querySelector('[class*="detBadge"]').textContent).toContain(tr("detectableAuto"));
  expect(methodCell.querySelectorAll('[class*="rubricTargetItem_"]')).toHaveLength(1);

  await act(async () => {
    container.querySelector('[aria-controls="rubric-detail-0"]').click();
  });
  const detail = container.querySelector("#rubric-detail-0");

  // 展開內容就在檢測方式那一格裡，摘要晶片換成完整步驟
  expect(methodCell.contains(detail)).toBe(true);
  expect(methodCell.querySelectorAll('[class*="rubricTargetItem_"]')).toHaveLength(0);
  expect(detail.querySelector("dl")).toBeNull();

  const machine = detail.querySelector('[class*="rubricMethodMachine"]');
  expect(machine.textContent).toContain(tr("detailMachine")); // 報讀器用的欄名
  expect(machine.textContent).toContain("Nginx Web");
  expect(machine.textContent).toContain("環境機器 · LXC");

  const steps = detail.querySelector("ol");
  expect(steps.getAttribute("aria-label")).toBe(tr("detailSteps"));
  expect(steps.textContent).toContain(tr("stepRunCommand"));
  expect(detail.querySelector("code").textContent).toBe("systemctl is-active php8.2-fpm");
  // 只有一步時不編號
  expect(steps.className).not.toMatch(/Numbered/);

  // 徽章已經寫「可自動檢查」，不再多一行「系統自動判定」
  expect(detail.textContent).not.toContain(tr("judgeSystem"));
  expect(detail.textContent).not.toContain("command");
});

test("徽章看不出由誰判定時（缺少資訊＋導師核查）才補判定方式，缺少的資訊排在最後", async () => {
  const container = await mountTable([{
    ...ITEM,
    detectable: "partial",
    judgement_mode: "teacher",
    missing_information: ["網站根目錄"],
  }]);
  await act(async () => {
    container.querySelector('[aria-controls="rubric-detail-0"]').click();
  });
  const notes = [...container.querySelectorAll('#rubric-detail-0 [class*="rubricMethodNote"]')].map((note) => note.textContent);

  expect(notes).toEqual([
    tr("labelValue", { label: tr("detectablePartial"), value: "網站根目錄" }),
    tr("labelValue", { label: tr("detailJudgement"), value: tr("judgeTeacher") }),
  ]);
});

test("檢測方式旁的 ⓘ 點一下跳出說明，點提示本身不收合整列，按 Esc 播完離場動畫後收起", async () => {
  const container = await mountTable([ITEM]);
  const methodCell = container.querySelector('[class*="rubricDescriptionCell"]');
  const info = methodCell.querySelector('button[aria-label="' + tr("methodInfoAria") + '"]');
  // 提示 portal 到 body
  const tip = () => document.body.querySelector('[role="note"]');

  // 點 ⓘ 只開提示，不展開整列
  await clickOn(info);
  expect(info.getAttribute("aria-expanded")).toBe("true");
  expect(tip().textContent).toBe(tr("detailDesc"));
  expect(container.querySelector("#rubric-detail-0")).toBeNull();

  await clickOn(tip());
  expect(container.querySelector("#rubric-detail-0")).toBeNull();

  await act(async () => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
  // 先留著播 130ms 離場動畫（methodInfoOut），之後才卸載
  expect(info.getAttribute("aria-expanded")).toBe("false");
  expect(tip().className).toMatch(/methodInfoOut/);
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 160));
  });
  expect(tip()).toBeNull();
});
