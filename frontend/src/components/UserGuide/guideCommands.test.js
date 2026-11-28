import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import {
  clearArrivalCommand,
  executeGuideCommand,
  guidePathOf,
  listGuideSteps,
  peekArrivalCommand,
  registerGuideApi,
  requestGuideOnArrival,
  runGuideCommandAt,
} from "./guideCommands";

let api;
let unregister;

beforeEach(() => {
  clearArrivalCommand();
  api = {
    listSteps: vi.fn(() => [{ id: "0", title: "資源配額" }]),
    tour: vi.fn(),
    spotStep: vi.fn(() => true),
    spotSelector: vi.fn(() => true),
  };
  unregister = registerGuideApi(api);
});

afterEach(() => {
  unregister();
  vi.useRealTimers();
});

describe("沒有 UserGuide 時", () => {
  test("所有命令安靜地不做事", () => {
    unregister();
    expect(listGuideSteps()).toEqual([]);
    expect(executeGuideCommand({ type: "tour" })).toBe(false);
    expect(executeGuideCommand({ type: "spot", stepId: "1" })).toBe(false);
  });

  test("解除註冊只會拿掉自己，不會誤刪後來註冊的那一個", () => {
    const next = { listSteps: () => [{ id: "9", title: "新的" }], tour: vi.fn(), spotStep: vi.fn(), spotSelector: vi.fn() };
    registerGuideApi(next);
    unregister();
    expect(listGuideSteps()).toEqual([{ id: "9", title: "新的" }]);
  });
});

describe("立刻執行", () => {
  test("完整導覽、指某一步、指任意錨點各自轉給對應的實作", () => {
    expect(listGuideSteps()).toEqual([{ id: "0", title: "資源配額" }]);
    expect(executeGuideCommand({ type: "tour" })).toBe(true);
    expect(api.tour).toHaveBeenCalledTimes(1);

    expect(executeGuideCommand({ type: "spot", stepId: 3 })).toBe(true);
    expect(api.spotStep).toHaveBeenCalledWith("3");

    executeGuideCommand({ type: "spot", selector: '[data-guide="firewall-create"]', title: "發布對外網址", text: "填連接埠" });
    expect(api.spotSelector).toHaveBeenCalledWith({ selector: '[data-guide="firewall-create"]', title: "發布對外網址", text: "填連接埠" });
  });

  test("不認得的命令與空命令回 false", () => {
    expect(executeGuideCommand(null)).toBe(false);
    expect(executeGuideCommand({ type: "unknown" })).toBe(false);
  });
});

describe("換頁之後才做的命令", () => {
  test("只有到了那一頁才看得到，查詢字串與結尾斜線不影響比對", () => {
    const command = { type: "tour" };
    requestGuideOnArrival("/firewall?tab=rules", command);
    expect(peekArrivalCommand("/my-resources")).toBeNull();
    expect(peekArrivalCommand("/firewall/")).toBe(command);
    // 只看不取：真的執行了才由 UserGuide 清掉
    expect(peekArrivalCommand("/firewall")).toBe(command);
    clearArrivalCommand(command);
    expect(peekArrivalCommand("/firewall")).toBeNull();
  });

  test("清別人的命令不會清掉現在等著的那一個；後下的蓋掉前一個", () => {
    const first = { type: "tour" };
    const second = { type: "spot", stepId: "2" };
    requestGuideOnArrival("/firewall", first);
    requestGuideOnArrival("/jobs", second);
    clearArrivalCommand(first);
    expect(peekArrivalCommand("/firewall")).toBeNull();
    expect(peekArrivalCommand("/jobs")).toBe(second);
  });

  test("太久沒到就作廢，免得很久以後才突然跳出導覽", () => {
    vi.useFakeTimers();
    requestGuideOnArrival("/firewall", { type: "tour" });
    vi.advanceTimersByTime(16_000);
    expect(peekArrivalCommand("/firewall")).toBeNull();
  });

  test("已經在那一頁就立刻做，否則記下來等換頁", () => {
    expect(runGuideCommandAt("/my-resources?x=1", "/my-resources", { type: "tour" })).toBe(true);
    expect(api.tour).toHaveBeenCalledTimes(1);
    expect(peekArrivalCommand("/my-resources")).toBeNull();

    const command = { type: "tour" };
    expect(runGuideCommandAt("/firewall", "/my-resources", command)).toBe(false);
    expect(api.tour).toHaveBeenCalledTimes(1);
    expect(peekArrivalCommand("/firewall")).toBe(command);
  });
});

test("guidePathOf 只留路徑", () => {
  expect(guidePathOf("/class-setup?classId=42&step=3")).toBe("/class-setup");
  expect(guidePathOf("/firewall/#rules")).toBe("/firewall");
  expect(guidePathOf("")).toBe("/");
  expect(guidePathOf(undefined)).toBe("/");
});
