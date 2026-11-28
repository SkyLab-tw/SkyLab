// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import UserGuide from "./UserGuide";
import {
  clearArrivalCommand,
  executeGuideCommand,
  listGuideSteps,
  peekArrivalCommand,
  requestGuideOnArrival,
} from "./guideCommands";

const state = vi.hoisted(() => ({ user: null, updateUser: vi.fn(), markSeen: vi.fn() }));
const route = vi.hoisted(() => ({ pathname: "/my-resources" }));
vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => state }));
vi.mock("../../services/account", () => ({ AccountService: { markUserGuideSeen: state.markSeen } }));
vi.mock("react-router-dom", () => ({ useLocation: () => ({ pathname: route.pathname }) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key) => key }) }));

let root;
let host;

/* 我的資源頁：配額、申請鈕與一台機器在畫面上；主控台鈕、電源選單、開詳情不在（沒展開） */
function mountResourcesPage() {
  document.body.innerHTML = [
    "<h1>我的資源</h1><span data-user-guide-slot></span>",
    '<div data-guide="resource-quota"></div>',
    '<button data-guide="resource-request"></button>',
    '<div data-guide="resource-card"></div>',
  ].join("");
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  localStorage.clear();
  sessionStorage.clear();
  clearArrivalCommand();
  route.pathname = "/my-resources";
  /* 老師：我的資源頁沒有自動導覽，這裡看到的導覽都是命令叫出來的 */
  state.user = { id: "u1", role: "teacher", seen_user_guides: [] };
  state.markSeen.mockReset().mockResolvedValue({ seen_user_guides: ["my-resources"] });
  state.updateUser.mockReset();
  mountResourcesPage();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  vi.useRealTimers();
  document.body.innerHTML = "";
});

async function render() {
  await act(async () => root.render(<UserGuide />));
}

/* 聚光框要等目標定位（最多 360ms 的校正）才畫出面板；自動開導覽另外從 500ms 起跳。
   act 結束時才會重繪，所以分兩段推時間 */
async function advance(ms = 600) {
  await act(async () => vi.advanceTimersByTimeAsync(ms));
  await act(async () => vi.advanceTimersByTimeAsync(ms));
}

const dialog = () => document.querySelector('[role="dialog"]');
const buttonByText = (text) => [...document.querySelectorAll("button")].find((button) => button.textContent.includes(text));
const SEEN_KEY = "skylab:user-guide:seen:u1:my-resources";

test("列出現在指得到的步驟：目標在畫面上的才算，會換頁的那一步不列", async () => {
  await render();
  expect(listGuideSteps()).toEqual([
    { id: "0", title: "UserGuide.myResources.step1.title" },
    { id: "1", title: "UserGuide.myResources.request.title" },
    { id: "2", title: "UserGuide.myResources.row.title" },
  ]);

  // 更多操作鈕出現後，要先按它才看得到的電源選單也指得到（聚光燈會替你按）
  const more = document.createElement("button");
  more.dataset.guide = "resource-more-actions";
  document.body.append(more);
  expect(listGuideSteps().map((step) => step.id)).toEqual(["0", "1", "2", "4"]);
});

test("卸載後不再回報步驟，命令也不做事", async () => {
  await render();
  await act(async () => root.unmount());
  expect(listGuideSteps()).toEqual([]);
  expect(executeGuideCommand({ type: "spot", stepId: "0" })).toBe(false);
  root = createRoot(host);
});

test("單步打光：只顯示那一步與「知道了」，不算看過導覽", async () => {
  await render();
  await act(async () => { executeGuideCommand({ type: "spot", stepId: "1" }); });
  await advance();

  expect(dialog()).not.toBeNull();
  expect(dialog().textContent).toContain("UserGuide.myResources.request.title");
  expect(dialog().textContent).toContain("UserGuide.myResources.request.text");
  expect(dialog().textContent).toContain("UserGuide.spotSubtitle");
  // 沒有完整導覽的進度與跳過
  expect(dialog().textContent).not.toContain("UserGuide.skipButton");
  expect(localStorage.getItem(SEEN_KEY)).toBeNull();
  expect(state.markSeen).not.toHaveBeenCalled();

  await act(async () => buttonByText("UserGuide.spotDismissButton").click());
  expect(dialog()).toBeNull();
  expect(localStorage.getItem(SEEN_KEY)).toBeNull();
});

test("單步打光也能指任意錨點，標題與說明由呼叫端提供", async () => {
  await render();
  await act(async () => {
    executeGuideCommand({ type: "spot", selector: '[data-guide="resource-card"]', title: "確認服務", text: "確認服務已啟動" });
  });
  await advance();
  expect(dialog().textContent).toContain("確認服務");
  expect(dialog().textContent).toContain("確認服務已啟動");
});

test("要指的東西不在畫面上：等不到就安靜地收掉，不留看不見的遮罩", async () => {
  await render();
  await act(async () => {
    executeGuideCommand({ type: "spot", selector: '[data-guide="not-on-this-page"]', title: "不存在" });
  });
  // 找目標最多重試 40 次、每次 100ms
  await advance(2500);
  expect(dialog()).toBeNull();
  // 之後再指別的還是正常
  await act(async () => { executeGuideCommand({ type: "spot", stepId: "0" }); });
  await advance();
  expect(dialog().textContent).toContain("UserGuide.myResources.step1.title");
});

test("不認得的步驟編號不做事", async () => {
  await render();
  let result;
  await act(async () => { result = executeGuideCommand({ type: "spot", stepId: "99" }); });
  await advance();
  expect(result).toBe(false);
  expect(dialog()).toBeNull();
});

test("完整導覽命令：開始這一頁的導覽，照常記為看過", async () => {
  await render();
  await act(async () => { executeGuideCommand({ type: "tour" }); });
  await advance();
  expect(dialog()).not.toBeNull();
  expect(dialog().textContent).toContain("UserGuide.skipButton");
  expect(localStorage.getItem(SEEN_KEY)).toBe("completed");
});

test("換頁後的完整導覽：到了那一頁自動開始，即使看過了、也不是學生", async () => {
  localStorage.setItem(SEEN_KEY, "completed");
  state.user = { id: "u1", role: "teacher", seen_user_guides: ["my-resources"] };
  requestGuideOnArrival("/my-resources", { type: "tour" });
  await render();
  await advance();
  expect(dialog()).not.toBeNull();
  expect(dialog().textContent).toContain("UserGuide.skipButton");
  // 命令用過就清掉，重新 render 不會再開一次
  expect(peekArrivalCommand("/my-resources")).toBeNull();
});

test("換頁後的單步打光：到了那一頁把指定的地方亮出來", async () => {
  route.pathname = "/dashboard";
  await render();
  requestGuideOnArrival("/my-resources", { type: "spot", stepId: "2" });

  route.pathname = "/my-resources";
  await render();
  await advance();
  expect(dialog().textContent).toContain("UserGuide.myResources.row.title");
  expect(peekArrivalCommand("/my-resources")).toBeNull();
  expect(localStorage.getItem(SEEN_KEY)).toBeNull();
});

test("別頁的命令不會在這一頁被執行", async () => {
  requestGuideOnArrival("/firewall", { type: "tour" });
  await render();
  await advance();
  expect(dialog()).toBeNull();
  expect(peekArrivalCommand("/firewall")).toEqual({ type: "tour" });
});
