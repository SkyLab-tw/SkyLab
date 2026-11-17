// @vitest-environment happy-dom
/* 窄版收欄（useTableFit）：表格區變窄時，機器數、資源合計、版本收進名稱底下，使用班級、提供方式收到狀態徽章底下；
   名稱、狀態、操作永遠在，整列點下去照樣開啟、操作鈕的導覽錨點還在 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { withQueryClient } from "../../../queries/testing";
import CourseTemplateManagementPage from "./CourseTemplateManagementPage";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  navigate: vi.fn(),
  /* 帶數量的字串把數量接在鍵後面，才看得出收進來的是哪一筆的值 */
  t: (key, options) => (options?.count != null ? `${key}:${options.count}` : key),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../../services/courseEnvironments", () => ({ CourseEnvironmentsService: { list: mocks.list, remove: vi.fn() } }));
vi.mock("react-i18next", async (importOriginal) => ({ ...await importOriginal(), useTranslation: () => ({ t: mocks.t }) }));
vi.mock("react-router-dom", async (importOriginal) => ({ ...await importOriginal(), useNavigate: () => mocks.navigate }));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("../../../components/ConfirmDialog/ConfirmProvider", () => ({ useConfirm: () => vi.fn() }));
vi.mock("../../../components/PageHeader/PageHeader", () => ({ default: () => null }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
let tableWidth;
let host;
let root;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  /* happy-dom 沒有版面：表格區（data-guide="course-tpl-table"）的寬度由測試指定 */
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return this.getAttribute("data-guide") === "course-tpl-table" ? tableWidth : 0; },
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
  else delete HTMLElement.prototype.clientWidth;
});

/* 兩台機器（合計 6 CPU · 12 GB）、第 3 版、課程＋快速練習、2 個班級在用 */
const ENVIRONMENT = {
  id: "7",
  name: "Linux 實驗環境",
  status: "published",
  version: 3,
  usageScope: "both",
  classes: 2,
  nodes: [{ cpu: 2, memory: 4, disk: 20 }, { cpu: 4, memory: 8, disk: 40 }],
};

async function renderAt(width) {
  tableWidth = width;
  mocks.list.mockResolvedValue([ENVIRONMENT]);
  await act(async () => {
    root.render(withQueryClient(
      <MemoryRouter initialEntries={["/course-template-management"]}>
        <CourseTemplateManagementPage />
      </MemoryRouter>,
    ));
  });
  await flush();
}

const headers = () => [...host.querySelectorAll("thead th")].map((th) => th.textContent);
const firstRowCells = () => [...host.querySelector("tbody tr").children];
const cols = () => host.querySelectorAll("colgroup col").length;

test("寬到放得下全部欄（1124px）時不收欄，也沒有舊的 min-width 880", async () => {
  await renderAt(1200);
  expect(headers()).toHaveLength(8);
  expect(host.querySelector("table").style.minWidth).toBe("1124px");
  expect(firstRowCells()[0].querySelector("small")).toBeNull();
});

test("1366 筆電（約 929px）：版本、資源合計收進名稱底下，依欄位順序", async () => {
  await renderAt(929);
  expect(headers()).toEqual([
    "CourseTemplateManagementPage.thName",
    "CourseTemplateManagementPage.thMachinesPerStudent",
    "CourseTemplateManagementPage.thProvideMode",
    "CourseTemplateManagementPage.thUsingClasses",
    "CourseTemplateManagementPage.thStatus",
    "CourseTemplateManagementPage.thActions",
  ]);
  expect(cols()).toBe(6);
  const folded = firstRowCells()[0].querySelector("small").textContent;
  expect(folded).toBe("CourseTemplateManagementPage.resourceSummary · v3");
  expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
});

test.each([
  ["1100 寬視窗", 678],
  ["1440 開著 AI 助手", 567],
])("%s（約 %ipx）：只剩名稱、提供方式、狀態、操作", async (_, width) => {
  await renderAt(width);
  expect(headers()).toEqual([
    "CourseTemplateManagementPage.thName",
    "CourseTemplateManagementPage.thProvideMode",
    "CourseTemplateManagementPage.thStatus",
    "CourseTemplateManagementPage.thActions",
  ]);
  const [name, usage, status] = firstRowCells();
  expect(name.querySelector("small").textContent).toBe(
    "CourseTemplateManagementPage.machinesPerStudentUnit:2 · CourseTemplateManagementPage.resourceSummary · v3",
  );
  expect(usage.textContent).toBe("CourseTemplateManagementPage.usageBoth");
  /* 使用班級收到狀態徽章底下；提供方式還有自己的欄，不重複寫 */
  expect([...status.querySelectorAll("small")].map((line) => line.textContent)).toEqual(["CourseTemplateManagementPage.classesCount:2"]);
  expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
});

test("手機（約 448px）：提供方式也收進狀態底下，全部收完不用橫捲；整列與操作照樣能用", async () => {
  await renderAt(448);
  expect(headers()).toEqual([
    "CourseTemplateManagementPage.thName",
    "CourseTemplateManagementPage.thStatus",
    "CourseTemplateManagementPage.thActions",
  ]);
  expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);

  const [, status, actions] = firstRowCells();
  expect(status.firstElementChild.textContent).toBe("CourseTemplateManagementPage.statusPublished");
  expect([...status.querySelectorAll("small")].map((line) => line.textContent)).toEqual([
    "CourseTemplateManagementPage.usageBoth",
    "CourseTemplateManagementPage.classesCount:2",
  ]);
  expect(actions.querySelector('[data-guide="course-tpl-row-actions"]')).not.toBeNull();

  await act(async () => { host.querySelector("tbody tr").click(); });
  expect(mocks.navigate).toHaveBeenCalledWith("/course-template-management/7");
});
