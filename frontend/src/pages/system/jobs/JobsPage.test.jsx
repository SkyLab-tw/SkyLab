// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import JobsPage from "./JobsPage";
import { createTestQueryClient, withQueryClient } from "../../../queries/testing";
import { jobKeys } from "../../../queries/jobs";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  t: (key) => key,
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../../services/jobs", () => ({ JobsService: { list: mocks.list } }));
vi.mock("../../../components/Jobs/JobDetailDialog", () => ({ default: () => null }));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("../../../components/PageHeader/PageHeader", () => ({ default: () => null }));
vi.mock("../../../components/LoadingState/LoadingState", () => ({ default: () => <div data-testid="loading" /> }));
vi.mock("../../../components/ErrorState/ErrorState", () => ({
  default: ({ onRetry }) => <button type="button" data-testid="error" onClick={onRetry}>retry</button>,
}));
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
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function job(id, kind) {
  return { id, kind, title: `job-${id}`, status: "completed", progress: 100 };
}

let host;
let root;
const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");

/* happy-dom 沒有版面：指定表格區（data-guide="jobs-table"）的寬度，useTableFit 才會收欄 */
function setTableWidth(width) {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return this.getAttribute("data-guide") === "jobs-table" ? width : 0; },
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
  else delete HTMLElement.prototype.clientWidth;
});

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function pickKind(kind) {
  await act(async () => host.querySelector(`[data-group="JobsPage.filterKind"] [data-value="${kind}"]`).click());
}

test("快速切換篩選時，較晚回來的舊條件結果不會蓋掉目前篩選的清單", async () => {
  const older = deferred();
  const newer = deferred();
  mocks.list
    .mockResolvedValueOnce({ items: [job("all", "vm_request")] })
    .mockReturnValueOnce(older.promise)
    .mockReturnValueOnce(newer.promise);

  await act(async () => root.render(withQueryClient(<JobsPage />)));
  await flush();

  await pickKind("vm_request");
  await pickKind("deletion");
  expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ kinds: ["deletion"] }));

  await act(async () => newer.resolve({ items: [job("del", "deletion")] }));
  await flush();
  await act(async () => older.resolve({ items: [job("vm", "vm_request")] }));
  await flush();

  expect(host.textContent).toContain("job-del");
  expect(host.textContent).not.toContain("job-vm");
  expect(host.querySelector('[data-testid="loading"]')).toBeNull();
});

test("換篩選期間先留著上一份清單，不閃回載入畫面", async () => {
  const pending = deferred();
  mocks.list
    .mockResolvedValueOnce({ items: [job("all", "vm_request")] })
    .mockReturnValueOnce(pending.promise);

  await act(async () => root.render(withQueryClient(<JobsPage />)));
  await flush();
  await pickKind("deletion");
  await flush();

  expect(host.querySelector('[data-testid="loading"]')).toBeNull();
  expect(host.textContent).toContain("job-all");

  await act(async () => pending.resolve({ items: [job("del", "deletion")] }));
  await flush();
  expect(host.textContent).toContain("job-del");
  expect(host.textContent).not.toContain("job-all");
});

test("換篩選失敗時跳 toast 並顯示錯誤狀態；背景重試又失敗不重複跳", async () => {
  mocks.list
    .mockResolvedValueOnce({ items: [job("all", "vm_request")] })
    .mockRejectedValueOnce(new Error("boom"))
    .mockRejectedValueOnce(new Error("boom again"));
  const client = createTestQueryClient();

  await act(async () => root.render(withQueryClient(<JobsPage />, client)));
  await flush();
  await pickKind("deletion");
  await flush();

  expect(mocks.toast.error).toHaveBeenCalledTimes(1);
  expect(mocks.toast.error).toHaveBeenCalledWith("boom");
  expect(host.querySelector('[data-testid="error"]')).not.toBeNull();
  /* 錯誤時不能顯示成「沒有結果」 */
  expect(host.textContent).not.toContain("JobsPage.emptyNoResult");

  await act(async () => { await client.refetchQueries({ queryKey: jobKeys.list({ limit: 200, kinds: ["deletion"] }) }); });
  await flush();
  expect(mocks.list).toHaveBeenCalledTimes(3);
  expect(mocks.toast.error).toHaveBeenCalledTimes(1);
});

describe("窄版收欄", () => {
  const detailed = {
    ...job("vm_request:1", "vm_request"),
    user_email: "a@campus.edu.tw",
    created_at: "2026-11-17T06:30:00Z",
    updated_at: "2026-11-17T06:35:00Z",
  };
  const headers = () => [...host.querySelectorAll("thead th")].map((th) => th.textContent);
  const cells = () => [...host.querySelectorAll("tbody td")].map((td) => td.textContent);

  test("約 800px：類型、申請人收進任務欄，更新時間接在建立時間底下", async () => {
    mocks.list.mockResolvedValue({ items: [detailed] });
    setTableWidth(800);
    await act(async () => root.render(withQueryClient(<JobsPage />)));
    await flush();

    expect(headers()).toEqual(["JobsPage.colTask", "JobsPage.colStatus", "JobsPage.colProgress", "JobsPage.colCreatedAt"]);
    const [name, status, , created] = cells();
    expect(name).toContain("JobsPage.kindVmRequest · vm_request:1");
    expect(name).toContain("a@campus.edu.tw");
    expect(created).toContain("JobsPage.colUpdatedAt");
    expect(status).not.toContain("JobsPage.colCreatedAt");
  });

  test("約 500px：只剩任務、狀態，進度與兩個時間依先後排在狀態徽章底下", async () => {
    mocks.list.mockResolvedValue({ items: [detailed] });
    setTableWidth(500);
    await act(async () => root.render(withQueryClient(<JobsPage />)));
    await flush();

    expect(headers()).toEqual(["JobsPage.colTask", "JobsPage.colStatus"]);
    const status = cells()[1];
    expect(status).toContain("JobsPage.statusCompleted");
    expect(status).toContain("100%");
    expect(status.indexOf("JobsPage.colCreatedAt")).toBeGreaterThan(-1);
    expect(status.indexOf("JobsPage.colUpdatedAt")).toBeGreaterThan(status.indexOf("JobsPage.colCreatedAt"));
    expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
  });
});

test("背景刷新失敗沿用現有清單、不跳 toast", async () => {
  mocks.list
    .mockResolvedValueOnce({ items: [job("all", "vm_request")] })
    .mockRejectedValueOnce(new Error("503"));
  const client = createTestQueryClient();

  await act(async () => root.render(withQueryClient(<JobsPage />, client)));
  await flush();
  await act(async () => { await client.refetchQueries({ queryKey: jobKeys.list({ limit: 200 }) }); });
  await flush();

  expect(mocks.list).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("job-all");
  expect(mocks.toast.error).not.toHaveBeenCalled();
});
