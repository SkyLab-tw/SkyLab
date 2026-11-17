// @vitest-environment happy-dom

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/*
 * 課堂監看熱力圖的版面：「需要注意」在學生格上方一條、圖例跟統計數字同一列；
 * 只有一台機器時不做分頁，只標出機器名稱與類型。
 */

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, test, vi } from "vitest";
import { notifyManager } from "@tanstack/react-query";
import { StudentMachines } from "./ClassWorkspacePage";
import { withQueryClient } from "../../../queries/testing";
import { TeachingClassesService } from "../../../services/teachingClasses";
import { ClassroomService } from "../../../services/classroom";
import i18n from "../../../i18n";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() } }));
vi.mock("../../../components/Classroom/ClassroomWatchDialog", () => ({ default: () => null }));
vi.mock("../../../components/ConfirmDialog/ConfirmProvider", () => ({ useConfirm: () => vi.fn() }));

const tr = (key, options) => i18n.t(`ClassWorkspacePage.${key}`, { ns: "teaching", ...options });

const STUDENTS = [
  { id: "s1", full_name: "Amy", email: "amy@example.com", machines: [{ vmid: 101, status: "running", machine_node_id: "n1" }] },
  { id: "s2", full_name: "Ben", email: "ben@example.com", machines: [{ vmid: 102, status: "running", machine_node_id: "n1" }] },
];

let cleanup = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
  notifyManager.setScheduler((cb) => setTimeout(cb, 0));
  vi.restoreAllMocks();
});

async function mount(item, usage) {
  notifyManager.setScheduler((cb) => cb());
  vi.spyOn(TeachingClassesService, "resourceUsage").mockResolvedValue({ items: usage });
  vi.spyOn(ClassroomService, "listClassBroadcastSources").mockResolvedValue([]);
  vi.spyOn(ClassroomService, "listSessions").mockResolvedValue([]);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(withQueryClient(<StudentMachines item={item} />));
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  cleanup = () => {
    act(() => root.unmount());
    container.remove();
  };
  return container;
}

const before = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("課堂監看熱力圖的版面", () => {
  test("只有一台機器時不做分頁，只標出名稱與類型；需要注意在學生格上方，沒狀況時只有一行字", async () => {
    const container = await mount(
      { id: "c1", nodes: [{ id: "n1", name: "ubuntu-server", resource_type: "qemu" }], students: STUDENTS },
      [{ vmid: 101, status: "running", cpu_usage_pct: 30 }, { vmid: 102, status: "running", cpu_usage_pct: 40 }],
    );
    const toolbar = container.querySelector('[data-guide="class-progress-toolbar"]');
    expect(toolbar.querySelector('[role="tablist"]')).toBeNull();
    expect(toolbar.textContent).toContain("ubuntu-server");
    expect(toolbar.textContent).toContain("VM");

    const attention = container.querySelector('[data-guide="class-progress-attention"]');
    const tiles = container.querySelector('[data-guide="class-progress-tiles"]');
    expect(before(attention, tiles)).toBe(true);
    expect(attention.textContent).toContain(tr("attentionEmpty"));
    expect(attention.querySelector("button")).toBeNull();

    // 圖例跟統計數字在同一列
    const legend = container.querySelector(`[aria-label="${tr("heatLegendAria")}"]`);
    expect(legend.parentElement.querySelector("dl")).toBeTruthy();
  });

  test("兩台以上才有機器分頁；高負載的學生在需要注意列成可點的小卡", async () => {
    const container = await mount(
      {
        id: "c1",
        nodes: [{ id: "n1", name: "Web", resource_type: "qemu" }, { id: "n2", name: "DB", resource_type: "lxc" }],
        students: STUDENTS,
      },
      [{ vmid: 101, status: "running", cpu_usage_pct: 92 }, { vmid: 102, status: "running", cpu_usage_pct: 40 }],
    );
    // 機器切換是共用 SegmentedControl：一台一段，預設選第一台
    const machineSwitch = container.querySelector(`[aria-label="${tr("selectMachineAria")}"]`);
    const machineButtons = [...machineSwitch.querySelectorAll("button")];
    expect(machineButtons.map((button) => button.textContent)).toEqual(["dnsWeb", "terminalDB"]);
    expect(machineButtons.map((button) => button.getAttribute("aria-pressed"))).toEqual(["true", "false"]);

    const attention = container.querySelector('[data-guide="class-progress-attention"]');
    const chips = attention.querySelectorAll("li");
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toContain("Amy");
    expect(chips[0].textContent).toContain("92%");
    expect(chips[0].querySelector("button").getAttribute("aria-label")).toBe(tr("openStudentMachineAria", { machine: "Web", name: "Amy" }));
  });
});
