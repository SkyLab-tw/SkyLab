import { useLayoutEffect, useState } from "react";

/**
 * 表格窄版（樣式規範「表格」規則四）：依表格區寬度把次要欄位收進主欄，
 * 收到底還放不下才橫捲，並固定第一欄（中間還留得下捲動空間時連最後一欄也固定）。
 *
 * columns 依表格欄位順序列出每欄的寬度與收合順序：
 *   [{ id: "name", width: 230 }, …, { id: "node", width: 85, fold: 1 }]
 *   fold 小的先收；沒有 fold 的欄永遠顯示（名稱、狀態、操作這類）。
 *   columns 要放模組層級（常數），每次 render 新建的話會一直重新量。
 *
 * 回傳的 fit 交給 `<DataTable fit={fit}>`，ref 掛在會橫捲的容器（.tableWrap／.tableScroll）：
 *   isFolded(id)  這欄是否已收起。DataTable 會跳過收起的表頭與儲存格；
 *                 收起的內容改畫在哪一欄由頁面決定（儲存格用 useTableFitContext() 判斷）
 *   foldedIds     收起的欄。DataTable 寫在 <table data-folded="node env">，
 *                 SCSS 可用 [data-folded~="env"] 調整窄版樣式
 *   widthOf(id)   欄寬，DataTable 用來畫 <colgroup>
 *   minWidth      目前顯示中各欄的寬度合計，給 <table> 的 min-width
 *   overflow      收到底仍放不下時橫捲並固定欄：null（放得下）、"start"（只固定第一欄）、
 *                 "both"（首尾欄都固定）。DataTable 寫在 data-overflow，table-base 依它固定
 *   pinLead       橫捲時從左邊固定幾欄：第一欄是勾選框時在它的欄位設 pinNext: true，
 *                 勾選框後面那欄（名稱）一起固定，捲動時才看得到是哪一列；預設 1
 *   pinOffset     固定兩欄時，第二欄離左邊的距離（第一欄的寬度）
 *
 * 量不到寬度（還沒掛上、測試環境）時不收任何欄，跟原本的表格一樣。
 */

/* 首尾欄都固定後，中間至少要留這麼寬給捲動的欄位，不然只固定第一欄：
   手機上名稱＋操作兩欄就佔滿畫面，中間只剩一條縫，捲了也看不到東西；操作還能捲過去按、或點列進詳情 */
const MIN_SCROLL_WINDOW = 160;

export function fitColumns(columns, available) {
  const total = columns.reduce((sum, column) => sum + column.width, 0);
  const folded = new Set();
  if (!(available > 0)) return { folded, minWidth: total, overflow: null, pinLead: 1, pinOffset: 0 };
  let width = total;
  const foldOrder = columns.filter((column) => column.fold != null).sort((a, b) => a.fold - b.fold);
  for (const column of foldOrder) {
    if (width <= available) break;
    folded.add(column.id);
    width -= column.width;
  }
  const shown = columns.filter((column) => !folded.has(column.id));
  /* 第一欄是勾選框（pinNext）時，跟後面那欄一起固定 */
  const pinLead = shown[0]?.pinNext && shown.length > 2 ? 2 : 1;
  const pinOffset = pinLead > 1 ? shown[0].width : 0;
  if (width <= available) return { folded, minWidth: width, overflow: null, pinLead, pinOffset };
  const leadWidth = shown.slice(0, pinLead).reduce((sum, column) => sum + column.width, 0);
  const pinnedBoth = leadWidth + shown[shown.length - 1].width;
  return {
    folded,
    minWidth: width,
    overflow: available - pinnedBoth >= MIN_SCROLL_WINDOW ? "both" : "start",
    pinLead,
    pinOffset,
  };
}

function buildFit(columns, available, ref) {
  const { folded, minWidth, overflow, pinLead, pinOffset } = fitColumns(columns, available);
  const widths = new Map(columns.map((column) => [column.id, column.width]));
  return {
    /* 收起哪些欄、寬度、是否溢出都一樣時沿用同一個物件，拖拉視窗不會每一像素都重畫整張表 */
    key: `${[...folded].join()}|${minWidth}|${overflow}`,
    ref,
    foldedIds: [...folded],
    isFolded: (id) => folded.has(id),
    widthOf: (id) => widths.get(id),
    minWidth,
    overflow,
    pinLead,
    pinOffset,
  };
}

export default function useTableFit(columns) {
  const [element, setElement] = useState(null);
  const [fit, setFit] = useState(() => buildFit(columns, 0, setElement));

  /* layout effect：第一次量完在畫面出現前就重排，不會先閃一下完整欄位再收 */
  useLayoutEffect(() => {
    if (!element) return undefined;
    const update = () => {
      const next = buildFit(columns, element.clientWidth, setElement);
      setFit((previous) => (previous.key === next.key ? previous : next));
    };
    update();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, columns]);

  return fit;
}
