// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { withQueryClient } from "../../../queries/testing";
import AiMonitoringPage from "./AiMonitoringPage";

const mocks = vi.hoisted(() => ({
  overview: vi.fn(),
  runtime: vi.fn(),
  listProxyCalls: vi.fn(),
  listTemplateCalls: vi.fn(),
  listUsersUsage: vi.fn(),
  createGrafanaSession: vi.fn(),
  t: (key) => key,
  toast: { error: vi.fn() },
}));

vi.mock("../../../services/aiMonitoring", () => ({
  AiMonitoringService: {
    overview: mocks.overview,
    runtime: mocks.runtime,
    listProxyCalls: mocks.listProxyCalls,
    listTemplateCalls: mocks.listTemplateCalls,
    listUsersUsage: mocks.listUsersUsage,
  },
}));
vi.mock("../../../services/monitoring", () => ({
  MonitoringService: { createGrafanaSession: mocks.createGrafanaSession },
}));
vi.mock("../../../i18n", () => ({ default: { language: "en" } }));
vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal(),
  useTranslation: () => ({ t: mocks.t }),
}));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("../../../components/LoadingState/LoadingState", () => ({ default: () => <div data-testid="loading" /> }));
vi.mock("../../../components/PageHeader/PageHeader", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../../../components/SegmentedControl/SegmentedControl", () => ({
  default: ({ options = [], value, onChange, ariaLabel }) => (
    <div data-group={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          data-value={option.value}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.badge != null ? <span>{option.badge}</span> : null}
        </button>
      ))}
    </div>
  ),
}));

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

function overviewWith(totalCalls) {
  return {
    summary: { total_calls: totalCalls, total_tokens: 0, error_rate: 0, failed_calls: 0 },
    series: [],
    model_breakdown: [],
  };
}

let root;
let host;

/* 明細分頁是共用 Tabs（role="tab"，導覽錨點 data-guide-tab="ai-monitoring-<value>"） */
const detailTab = (value) => host.querySelector(`[role="tab"][data-guide-tab="ai-monitoring-${value}"]`);

/* TanStack Query 的通知排在 setTimeout(0)：先等一個 timer tick 再等 microtask */
async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function renderPage() {
  await act(async () => { root.render(withQueryClient(<AiMonitoringPage />)); });
}

beforeEach(() => {
  vi.resetAllMocks();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  mocks.runtime.mockResolvedValue({ gateway: { status: "available", readiness: true }, models: [], summary: {} });
  mocks.listProxyCalls.mockResolvedValue({ data: [], count: 0 });
  mocks.listTemplateCalls.mockResolvedValue({ data: [], count: 0 });
  mocks.listUsersUsage.mockResolvedValue({ data: [], count: 0 });
  mocks.createGrafanaSession.mockResolvedValue({ enabled: false });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("AiMonitoringPage", () => {
  test("a slow response for the previous range does not overwrite the new range", async () => {
    const first = deferred();
    const second = deferred();
    mocks.overview
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    await renderPage();
    await flush();
    const ninety = host.querySelector('[data-group="AiMonitoringPage.rangeLabel"] [data-value="90d"]');
    await act(async () => { ninety.click(); });
    await flush();
    expect(mocks.overview).toHaveBeenCalledTimes(2);
    // 起訖在抓取時才算，key 只放區間代號；執行狀態與區間無關，換區間不重抓
    expect(mocks.overview.mock.calls[1][0]).toEqual({
      startDate: expect.any(String), endDate: expect.any(String), bucket: "day", compare: true, source: "all",
    });
    expect(mocks.runtime).toHaveBeenCalledTimes(1);

    await act(async () => { second.resolve(overviewWith(9090)); });
    await flush();
    await act(async () => { first.resolve(overviewWith(7777)); });
    await flush();

    expect(host.textContent).toContain("9,090");
    expect(host.textContent).not.toContain("7,777");
  });

  test("AI Gateway readiness alert opens the models tab on this page", async () => {
    mocks.overview.mockResolvedValue(overviewWith(1));
    mocks.runtime.mockRejectedValue(new Error("gateway down"));

    await renderPage();
    await flush();

    const proxyTab = detailTab("proxy");
    await act(async () => { proxyTab.click(); });
    expect(proxyTab.getAttribute("aria-selected")).toBe("true");

    const alertRow = [...host.querySelectorAll("button")].find((b) => b.textContent.includes("AiMonitoringPage.attentionGatewayTitle"));
    expect(alertRow).toBeTruthy();
    await act(async () => { alertRow.click(); });

    expect(detailTab("models").getAttribute("aria-selected")).toBe("true");
  });

  const buttonNamed = (text) => [...host.querySelectorAll("button")].find((b) => b.textContent.includes(text));

  test("明細一筆都還沒拿到就失敗：顯示錯誤＋重試、分頁數字是「—」，不會說成「沒有資料」", async () => {
    mocks.overview.mockResolvedValue(overviewWith(1));
    mocks.listProxyCalls.mockRejectedValue(new Error("down"));

    await renderPage();
    await flush();
    expect(detailTab("proxy").textContent).toContain("—");
    await act(async () => { detailTab("proxy").click(); });

    expect(host.textContent).toContain("Error.title");
    expect(host.textContent).not.toContain("AiMonitoringPage.emptyCallsTitle");

    mocks.listProxyCalls.mockResolvedValue({ data: [], count: 0 });
    await act(async () => { buttonNamed("Error.retry").click(); });
    await flush();

    expect(host.textContent).toContain("AiMonitoringPage.emptyCallsTitle");
    expect(detailTab("proxy").textContent).not.toContain("—");
  });

  test("模型分頁：總覽失敗但執行狀態有模型時照常列出；兩份都沒列才顯示錯誤", async () => {
    mocks.overview.mockRejectedValue(new Error("usage down"));
    mocks.runtime.mockResolvedValue({
      gateway: { status: "available", readiness: true },
      models: [{ name: "Qwen/Qwen2.5-7B", status: "online", healthy_deployments: 1, unhealthy_deployments: 0 }],
      summary: {},
    });

    await renderPage();
    await flush();
    expect(host.querySelector("table")).toBeTruthy();
    expect(host.textContent).not.toContain("Error.title");

    act(() => root.unmount());
    root = createRoot(host);
    mocks.runtime.mockResolvedValue({ gateway: { status: "available", readiness: true }, models: [], summary: {} });
    await renderPage();
    await flush();

    expect(host.textContent).toContain("Error.title");
    expect(host.textContent).not.toContain("AiMonitoringPage.emptyModelBreakdown");
    expect(detailTab("models").textContent).toContain("—");
  });

  test("搜尋框有字時可按 ✕ 清掉", async () => {
    mocks.overview.mockResolvedValue(overviewWith(1));
    await renderPage();
    await flush();

    const input = host.querySelector('input[aria-label="AiMonitoringPage.searchPlaceholderModels"]');
    expect(buttonNamed("close")).toBeUndefined();
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => {
      setValue.call(input, "qwen");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(input.value).toBe("qwen");

    await act(async () => { host.querySelector('button[aria-label="EmptyState.clearSearch"]').click(); });
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
  });
});

describe("AiMonitoringPage 窄版收欄", () => {
  const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  const headers = () => [...host.querySelectorAll("thead th")].map((th) => th.textContent);
  const cells = () => [...host.querySelectorAll("tbody td")].map((td) => td.textContent);

  /* happy-dom 沒有版面：指定表格區（直接包著 <table> 的 .tableWrap）的寬度，useTableFit 才會收欄 */
  function setTableWidth(width) {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get() { return this.firstElementChild?.tagName === "TABLE" ? width : 0; },
    });
  }

  afterEach(() => {
    if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
    else delete HTMLElement.prototype.clientWidth;
  });

  async function openTab(value) {
    const tab = detailTab(value);
    await act(async () => { tab.click(); });
    await flush();
  }

  beforeEach(() => {
    mocks.overview.mockResolvedValue({
      ...overviewWith(12),
      model_breakdown: [{ model_name: "Qwen/Qwen2.5-7B", total_calls: 12, total_tokens: 3400, failed_calls: 1, error_rate: 8.3, avg_latency_ms: 900 }],
    });
    mocks.runtime.mockResolvedValue({
      gateway: { status: "available", readiness: true },
      models: [{ name: "Qwen/Qwen2.5-7B", status: "online", healthy_deployments: 2, unhealthy_deployments: 0 }],
      summary: {},
    });
    mocks.listProxyCalls.mockResolvedValue({
      data: [{
        id: 1,
        created_at: "2026-11-17T06:30:00Z",
        request_id: "7443be10aaaa",
        user_full_name: "王小明",
        user_email: "a@campus.edu.tw",
        model_name: "Qwen/Qwen2.5-7B",
        request_type: "chat_completion",
        input_tokens: 1200,
        output_tokens: 345,
        request_duration_ms: 1200,
        first_token_ms: 350,
        e2e_output_tokens_per_second: 12.35,
        usage_reported: true,
        status: "success",
      }],
      count: 1,
    });
    mocks.listUsersUsage.mockResolvedValue({
      data: [{ user_id: "u1", user_full_name: "王小明", user_email: "a@campus.edu.tw", proxy_calls: 10, template_calls: 2, proxy_input_tokens: 1000, proxy_output_tokens: 500, avg_latency_ms: 800, error_rate: 5 }],
      count: 1,
    });
  });

  test("模型表在 1366 筆電（約 900px）只收部署狀態，接在 Runtime 狀態徽章底下", async () => {
    setTableWidth(900);
    await renderPage();
    await flush();

    expect(headers()).toEqual([
      "AiMonitoringPage.colModel", "AiMonitoringPage.colRuntimeStatus", "AiMonitoringPage.colCallCount",
      "AiMonitoringPage.colTokensTotal", "AiMonitoringPage.colFailRate", "AiMonitoringPage.colAvgLatency",
    ]);
    expect(cells()[1]).toContain("AiMonitoringPage.deploymentCount");
    expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
  });

  test("模型表在手機（約 400px）只剩模型與狀態，呼叫統計依欄位順序接在狀態底下", async () => {
    setTableWidth(400);
    await renderPage();
    await flush();

    expect(headers()).toEqual(["AiMonitoringPage.colModel", "AiMonitoringPage.colRuntimeStatus"]);
    const runtime = cells()[1];
    expect(runtime).toContain("AiMonitoringPage.modelStatus_online");
    expect(runtime).toContain("AiMonitoringPage.colCallCount 12");
    const order = ["colCallCount", "colTokensTotal 3.4K", "colFailRate 8.3%", "colAvgLatency 900ms"].map((key) => runtime.indexOf(`AiMonitoringPage.${key}`));
    expect(order.every((index) => index > -1)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
  });

  test("呼叫紀錄在 1440（約 960px）：Token 證據、輸出接在輸入底下，速度接在耗時底下，類型收進時間欄", async () => {
    setTableWidth(960);
    await renderPage();
    await flush();
    await openTab("proxy");

    expect(headers()).toEqual([
      "AiMonitoringPage.colTime", "AiMonitoringPage.colUser", "AiMonitoringPage.colModel",
      "AiMonitoringPage.colInput", "AiMonitoringPage.colDuration", "AiMonitoringPage.colStatus",
    ]);
    const [time, , , input, duration, status] = cells();
    expect(time).toContain("chat_completion");
    expect(input).toContain("1.2K");
    expect(input).toContain("AiMonitoringPage.colOutput 345");
    expect(input).toContain("success");
    expect(duration).toContain("AiMonitoringPage.colFirstToken 350ms");
    expect(duration).toContain("12.35 tok/s");
    expect(status).not.toContain("AiMonitoringPage.colInput");
  });

  test("呼叫紀錄在 1366 筆電（約 900px）：輸入也收起時，Token 一組整個搬到狀態底下", async () => {
    setTableWidth(900);
    await renderPage();
    await flush();
    await openTab("proxy");

    expect(headers()).not.toContain("AiMonitoringPage.colInput");
    const status = cells().at(-1);
    expect(status).toContain("AiMonitoringPage.colInput 1.2K · AiMonitoringPage.colOutput 345");
    expect(status.lastIndexOf("success")).toBeGreaterThan(status.indexOf("AiMonitoringPage.colOutput"));
  });

  test("呼叫紀錄在手機（約 400px）只剩時間與狀態：誰、呼叫什麼在時間底下，耗時與速度在狀態底下", async () => {
    setTableWidth(400);
    await renderPage();
    await flush();
    await openTab("proxy");

    expect(headers()).toEqual(["AiMonitoringPage.colTime", "AiMonitoringPage.colStatus"]);
    const [time, status] = cells();
    expect(time).toContain("7443be10");
    expect(time).toContain("王小明 · a@campus.edu.tw");
    expect(time).toContain("Qwen/Qwen2.5-7B");
    const order = ["AiMonitoringPage.colInput", "AiMonitoringPage.colDuration 1.2s", "AiMonitoringPage.colFirstToken 350ms", "12.35 tok/s"].map((text) => status.indexOf(text));
    expect(order.every((index) => index > -1)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
  });

  test("使用者表在手機（約 400px）只剩使用者與呼叫次數，Tokens、延遲、失敗率接在呼叫次數底下", async () => {
    setTableWidth(400);
    await renderPage();
    await flush();
    await openTab("users");

    expect(headers()).toEqual(["AiMonitoringPage.colUser", "AiMonitoringPage.colCallCount"]);
    const calls = cells()[1];
    expect(calls).toContain("12");
    const order = ["colTokensTotal 1.5K", "colAvgLatency 800ms", "colFailRate 5%"].map((key) => calls.indexOf(`AiMonitoringPage.${key}`));
    expect(order.every((index) => index > -1)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  test("使用者表在 1366 筆電（約 900px）不用收欄", async () => {
    setTableWidth(900);
    await renderPage();
    await flush();
    await openTab("users");

    expect(headers()).toHaveLength(5);
  });
});
