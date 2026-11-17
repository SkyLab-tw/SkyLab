// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { createColumnHelper, useTable } from "@tanstack/react-table";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import DataTable, { DataTableCells } from "./DataTable";
import { baseFeatures } from "./features";
import { useTableFitContext } from "./TableFitContext";
import useTableFit, { fitColumns } from "../../hooks/useTableFit";

/*
 * 表格窄版收欄（樣式規範「表格」規則四）：表格區不夠寬時依 fold 順序收起次要欄位，
 * 收到底仍放不下才標 data-overflow（table-base 會固定首尾欄、橫捲）。
 */

const FIT_COLUMNS = Object.freeze([
  { id: "name", width: 200 },
  { id: "node", width: 100, fold: 1 },
  { id: "status", width: 150 },
  { id: "ip", width: 150, fold: 2 },
  { id: "actions", width: 100 },
]);

const columnHelper = createColumnHelper();

function NameCell({ row }) {
  const fit = useTableFitContext();
  return <>{row.original.name}{fit.isFolded("node") && <small> · {row.original.node}</small>}</>;
}

const columns = columnHelper.columns([
  columnHelper.display({ id: "name", header: "Name", cell: NameCell }),
  columnHelper.display({ id: "node", header: "Node", cell: ({ row }) => row.original.node }),
  columnHelper.display({ id: "status", header: "Status", cell: () => "running" }),
  columnHelper.display({ id: "ip", header: "IP", cell: () => "10.0.0.1" }),
  columnHelper.display({ id: "actions", header: "", cell: () => <button type="button">open</button> }),
]);

const ITEMS = [{ id: "a", name: "web", node: "pve-01" }];

/* 自己畫 <td> 的列（像群組列）也要跟著跳過收起的欄 */
function HandWrittenRow() {
  const fit = useTableFitContext();
  return (
    <tr data-hand>
      <td>group</td>
      {!fit.isFolded("node") && <td>pve-02</td>}
      <td>ok</td>
      {!fit.isFolded("ip") && <td>2/3</td>}
      <td />
    </tr>
  );
}

function FitTable() {
  const fit = useTableFit(FIT_COLUMNS);
  const table = useTable({ features: baseFeatures, columns, data: ITEMS, getRowId: (item) => item.id });
  return (
    <div ref={fit.ref} data-wrap>
      <DataTable
        table={table}
        fit={fit}
        renderRow={(row) => <tr key={row.id} data-row><DataTableCells row={row} /></tr>}
      >
        <HandWrittenRow />
      </DataTable>
    </div>
  );
}

let host;
let root;
let wrapWidth;
let resizeCallbacks;
const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
const originalResizeObserver = globalThis.ResizeObserver;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  wrapWidth = 0;
  resizeCallbacks = [];
  /* happy-dom 沒有版面，表格區寬度由測試指定；ResizeObserver 換成手動觸發 */
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return this.hasAttribute("data-wrap") ? wrapWidth : 0; },
  });
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; }
    observe() { resizeCallbacks.push(this.callback); }
    disconnect() { resizeCallbacks = resizeCallbacks.filter((callback) => callback !== this.callback); }
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
  globalThis.ResizeObserver = originalResizeObserver;
});

const headers = () => [...host.querySelectorAll("thead th")].map((th) => th.textContent);
const colWidths = () => [...host.querySelectorAll("colgroup col")].map((col) => col.style.width);
const handCells = () => [...host.querySelectorAll("tr[data-hand] td")].map((td) => td.textContent);

describe("fitColumns", () => {
  test("folds columns in fold order only until the rest fits", () => {
    expect(fitColumns(FIT_COLUMNS, 800)).toMatchObject({ minWidth: 700, overflow: null });
    expect([...fitColumns(FIT_COLUMNS, 800).folded]).toEqual([]);

    const narrow = fitColumns(FIT_COLUMNS, 650);
    expect([...narrow.folded]).toEqual(["node"]);
    expect(narrow).toMatchObject({ minWidth: 600, overflow: null });

    const narrower = fitColumns(FIT_COLUMNS, 500);
    expect([...narrower.folded]).toEqual(["node", "ip"]);
    expect(narrower).toMatchObject({ minWidth: 450, overflow: null });
  });

  test("still too narrow after every fold: scroll with the first column pinned; the last one too only when the middle keeps room to scroll", () => {
    /* 名稱 200＋操作 100 一起固定後中間只剩 100px：只固定第一欄 */
    const tight = fitColumns(FIT_COLUMNS, 400);
    expect([...tight.folded]).toEqual(["node", "ip"]);
    expect(tight).toMatchObject({ minWidth: 450, overflow: "start" });

    /* 中間欄很寬、首尾欄窄：固定兩欄後還留 180px 可捲，首尾都固定 */
    const wideMiddle = [{ id: "a", width: 100 }, { id: "b", width: 300 }, { id: "c", width: 100 }];
    expect(fitColumns(wideMiddle, 380)).toMatchObject({ minWidth: 500, overflow: "both" });
  });

  test("a leading checkbox column (pinNext) pins the next visible column with it", () => {
    const withSelect = [{ id: "select", width: 40, pinNext: true }, { id: "name", width: 200 }, { id: "status", width: 150 }, { id: "actions", width: 100 }];
    /* 放得下：不橫捲，但仍算出固定兩欄與第二欄的位移，給收到底時用 */
    expect(fitColumns(withSelect, 600)).toMatchObject({ overflow: null, pinLead: 2, pinOffset: 40 });
    /* 勾選＋名稱 240、操作 100，中間只剩 60px：只固定前兩欄 */
    expect(fitColumns(withSelect, 400)).toMatchObject({ overflow: "start", pinLead: 2, pinOffset: 40 });
    /* 沒有 pinNext 時照舊只固定第一欄 */
    expect(fitColumns(FIT_COLUMNS, 400)).toMatchObject({ pinLead: 1, pinOffset: 0 });
  });

  test("no width measured yet (not mounted, tests): nothing folds", () => {
    expect(fitColumns(FIT_COLUMNS, 0)).toMatchObject({ minWidth: 700, overflow: null });
    expect([...fitColumns(FIT_COLUMNS, 0).folded]).toEqual([]);
  });
});

describe("DataTable fit", () => {
  test("wide enough: every column, colgroup from the fit widths, min-width is the total", async () => {
    wrapWidth = 900;
    await act(async () => { root.render(<FitTable />); });

    expect(headers()).toEqual(["Name", "Node", "Status", "IP", ""]);
    expect(colWidths()).toEqual(["200px", "100px", "150px", "150px", "100px"]);
    const table = host.querySelector("table");
    expect(table.style.minWidth).toBe("700px");
    expect(table.hasAttribute("data-overflow")).toBe(false);
    expect(handCells()).toEqual(["group", "pve-02", "ok", "2/3", ""]);
  });

  test("narrow: folded columns drop out of header, colgroup, data rows and hand-written rows; the main cell shows the folded value", async () => {
    wrapWidth = 500;
    await act(async () => { root.render(<FitTable />); });

    expect(headers()).toEqual(["Name", "Status", ""]);
    expect(colWidths()).toEqual(["200px", "150px", "100px"]);
    expect(host.querySelector("table").style.minWidth).toBe("450px");
    const dataCells = [...host.querySelectorAll("tr[data-row] td")].map((td) => td.textContent);
    expect(dataCells).toEqual(["web · pve-01", "running", "open"]);
    expect(handCells()).toEqual(["group", "ok", ""]);
  });

  test("follows the container when it is resized; marks data-overflow once even the folded table does not fit", async () => {
    wrapWidth = 900;
    await act(async () => { root.render(<FitTable />); });
    expect(headers()).toHaveLength(5);

    wrapWidth = 650;
    await act(async () => { resizeCallbacks.forEach((callback) => callback()); });
    expect(headers()).toEqual(["Name", "Status", "IP", ""]);

    wrapWidth = 400;
    await act(async () => { resizeCallbacks.forEach((callback) => callback()); });
    expect(headers()).toEqual(["Name", "Status", ""]);
    const table = host.querySelector("table");
    expect(table.getAttribute("data-overflow")).toBe("start");
    expect(table.getAttribute("data-folded")).toBe("node ip");
  });
});
