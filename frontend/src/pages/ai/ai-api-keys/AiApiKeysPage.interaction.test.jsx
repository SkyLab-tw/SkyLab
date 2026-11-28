// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { createTestQueryClient, withQueryClient } from "../../../queries/testing";
import AiApiKeysPage from "./AiApiKeysPage";

const mocks = vi.hoisted(() => ({
  listAllCredentials: vi.fn(),
  t: (key) => key,
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../../services/aiApi", () => ({
  AiApiService: { listAllCredentials: mocks.listAllCredentials, deleteCredential: vi.fn() },
}));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("../../../components/PageHeader/PageHeader", () => ({ default: () => null }));
vi.mock("../../../components/LoadingState/LoadingState", () => ({ default: () => <div data-testid="loading" /> }));
vi.mock("../../../components/SegmentedControl/SegmentedControl", () => ({
  default: ({ options = [], onChange, ariaLabel }) => (
    <div data-group={ariaLabel}>
      {options.map((option) => (
        <button key={option.value} type="button" data-value={option.value} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  ),
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal(),
  useTranslation: () => ({ t: mocks.t }),
}));

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

function page(name, status) {
  return { data: [{ id: name, api_key_name: name, status }], count: 1 };
}

let host;
let root;
const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");

/* happy-dom 沒有版面：指定表格區（data-guide="ai-keys-admin-table"）的寬度，useTableFit 才會收欄 */
function setTableWidth(width) {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return this.getAttribute("data-guide") === "ai-keys-admin-table" ? width : 0; },
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
  else delete HTMLElement.prototype.clientWidth;
});

/* setTimeout 是假的（搜尋框 debounce）：TanStack Query 的通知排在 setTimeout(0)，要推進假時鐘 0ms 才會送出 */
async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function pickStatus(status) {
  await act(async () => host.querySelector(`[data-group="AiApiKeysPage.statusTabsLabel"] [data-value="${status}"]`).click());
}

test("快速切換狀態分頁時，較晚回來的舊分頁結果不會蓋掉目前分頁的清單", async () => {
  const older = deferred();
  const newer = deferred();
  mocks.listAllCredentials
    .mockResolvedValueOnce(page("key-active", "active"))
    .mockReturnValueOnce(older.promise)
    .mockReturnValueOnce(newer.promise);

  await act(async () => root.render(withQueryClient(<AiApiKeysPage />, createTestQueryClient())));
  await flush();
  expect(host.textContent).toContain("key-active");

  await pickStatus("inactive");
  await pickStatus("all");
  expect(mocks.listAllCredentials).toHaveBeenLastCalledWith(expect.objectContaining({ status: undefined }));

  await act(async () => newer.resolve(page("key-all", "active")));
  await flush();
  await act(async () => older.resolve(page("key-inactive", "inactive")));
  await flush();

  expect(host.textContent).toContain("key-all");
  expect(host.textContent).not.toContain("key-inactive");
  expect(host.querySelector('[data-testid="loading"]')).toBeNull();
});

test("換分頁後這組條件載入失敗，背景重抓期間維持錯誤畫面，不閃回載入中或上一組條件的清單", async () => {
  /* TanStack v5 沒有資料時重抓會把 status 改回 pending，還會把上一組條件的清單放回來當佔位資料；
     錯誤畫面要維持到這次重抓的結果，同一個錯誤也不重複提示 */
  mocks.listAllCredentials
    .mockResolvedValueOnce(page("key-active", "active"))
    .mockRejectedValueOnce(new Error("inactive down"));
  const client = createTestQueryClient();

  await act(async () => root.render(withQueryClient(<AiApiKeysPage />, client)));
  await flush();
  expect(host.textContent).toContain("key-active");

  await pickStatus("inactive");
  await flush();
  expect(host.textContent).toContain("Error.retry");
  expect(host.textContent).not.toContain("key-active");
  expect(mocks.toast.error).toHaveBeenCalledTimes(1);

  let reject;
  mocks.listAllCredentials.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
  act(() => { client.refetchQueries({ queryKey: ["aiApi", "allCredentials"], type: "active" }); });
  await flush();
  /* 重抓還在途中：錯誤畫面照樣在 */
  expect(reject).toBeTypeOf("function");
  expect(host.querySelector('[data-testid="loading"]')).toBeNull();
  expect(host.textContent).not.toContain("key-active");
  expect(host.textContent).toContain("Error.retry");

  await act(async () => reject(new Error("inactive down")));
  await flush();
  expect(host.textContent).toContain("Error.retry");
  expect(mocks.toast.error).toHaveBeenCalledTimes(1);
});

describe("空清單的說法", () => {
  const titles = () => host.textContent;
  const clearButton = () => [...host.querySelectorAll("button")].find((button) => button.textContent.includes("EmptyState.clearFilters"));

  async function renderWith(response) {
    mocks.listAllCredentials.mockResolvedValue(response);
    await act(async () => root.render(withQueryClient(<AiApiKeysPage />, createTestQueryClient())));
    await flush();
  }

  test("全站一把金鑰都沒有：說「尚無金鑰紀錄」，不叫人清除篩選（預設的「啟用中」分頁不算篩選）", async () => {
    await renderWith({ data: [], count: 0, total_count: 0, active_count: 0, inactive_count: 0 });

    expect(titles()).toContain("AiApiKeysPage.emptyTitle");
    expect(titles()).not.toContain("AiApiKeysPage.emptyFilteredTitle");
    expect(clearButton()).toBeUndefined();
  });

  test("「啟用中」是空的、但已停用的還有：這個分頁是被分頁篩掉的，可以清除篩選看全部", async () => {
    await renderWith({ data: [], count: 0, total_count: 3, active_count: 0, inactive_count: 3 });

    expect(titles()).toContain("AiApiKeysPage.emptyFilteredTitle");
    expect(clearButton()).toBeDefined();

    mocks.listAllCredentials.mockResolvedValue({ ...page("key-old", "revoked"), total_count: 3, active_count: 0, inactive_count: 3 });
    await act(async () => clearButton().click());
    await flush();
    expect(mocks.listAllCredentials).toHaveBeenLastCalledWith(expect.objectContaining({ status: undefined }));
    expect(host.textContent).toContain("key-old");
  });

  test("搜尋不到東西：不管有沒有金鑰都是「沒有符合條件」", async () => {
    await renderWith({ data: [], count: 0, total_count: 0, active_count: 0, inactive_count: 0 });
    const input = host.querySelector('input[type="search"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "nobody");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    /* 搜尋框有 220ms 的 debounce */
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    await flush();

    expect(titles()).toContain("AiApiKeysPage.emptyFilteredTitle");
    expect(clearButton()).toBeDefined();
  });
});

describe("窄版收欄", () => {
  const detailed = {
    id: "k1",
    api_key_name: "lab-key",
    status: "active",
    user_full_name: "王小明",
    user_email: "a@campus.edu.tw",
    request_purpose: "期末專題",
    last_used_at: "2026-11-17T06:30:00Z",
    created_at: "2026-11-01T06:30:00Z",
  };
  const headers = () => [...host.querySelectorAll("thead th")].map((th) => th.textContent);
  const cells = () => [...host.querySelectorAll("tbody td")].map((td) => td.textContent);

  async function renderAt(width, item = detailed) {
    mocks.listAllCredentials.mockResolvedValue({ data: [item], count: 1 });
    setTableWidth(width);
    await act(async () => root.render(withQueryClient(<AiApiKeysPage />, createTestQueryClient())));
    await flush();
  }

  test("1366 筆電（約 929px）：建立日期接在活動底下，擁有者併進名稱底下的 Email 那一行", async () => {
    await renderAt(929);

    expect(headers()).toEqual([
      "AiApiKeysPage.colName", "AiApiKeysPage.detailPurpose", "AiApiKeysPage.detailActivity",
      "AiApiKeysPage.colStatus", "AiApiKeysPage.colActions",
    ]);
    const [name, , activity, status] = cells();
    expect(name).toContain("王小明 · a@campus.edu.tw");
    expect(activity).toContain("AiApiKeysPage.colCreatedAt");
    expect(status).not.toContain("AiApiKeysPage.colCreatedAt");
    expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
  });

  test("1100 寬視窗（約 678px）：申請用途也收進名稱底下，時間還在活動欄", async () => {
    await renderAt(678);

    expect(headers()).toEqual([
      "AiApiKeysPage.colName", "AiApiKeysPage.detailActivity", "AiApiKeysPage.colStatus", "AiApiKeysPage.colActions",
    ]);
    const name = host.querySelector("tbody td");
    expect(name.textContent).toContain("期末專題");
    expect(name.querySelector('[title="期末專題"]')).not.toBeNull();
  });

  test("開著 AI 助手（約 567px）：只剩金鑰、狀態、操作，兩個時間依先後排在狀態底下，導覽錨點跟著搬", async () => {
    await renderAt(567);

    expect(headers()).toEqual(["AiApiKeysPage.colName", "AiApiKeysPage.colStatus", "AiApiKeysPage.colActions"]);
    const statusCell = host.querySelectorAll("tbody td")[1];
    const status = statusCell.textContent;
    expect(status).toContain("AiApiKeysPage.statusActive");
    expect(status.indexOf("AiApiKeysPage.colCreatedAt")).toBeGreaterThan(-1);
    expect(status.indexOf("AiApiKeysPage.detailActivity")).toBeGreaterThan(status.indexOf("AiApiKeysPage.colCreatedAt"));
    expect(statusCell.querySelector('[data-guide="ai-keys-admin-activity"]')).not.toBeNull();
    expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
  });

  test("沒用過的金鑰收進狀態底下只寫「尚未使用」，不加欄名", async () => {
    await renderAt(567, { ...detailed, last_used_at: null });

    const status = cells()[1];
    expect(status).toContain("AiApiKeysPage.detailNeverUsed");
    expect(status).not.toContain("AiApiKeysPage.detailActivity");
  });

  test("手機（約 448px）收到底仍放不下：橫捲並固定第一欄", async () => {
    await renderAt(448);

    expect(headers()).toEqual(["AiApiKeysPage.colName", "AiApiKeysPage.colStatus", "AiApiKeysPage.colActions"]);
    expect(host.querySelector("table").getAttribute("data-overflow")).toBe("start");
  });
});
