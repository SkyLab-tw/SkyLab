/* 錨點選單的共用定位計算（hooks/useAnchoredMenu 的核心，PowerMenu、PortInput 等選單共用）——
   抽成純函式方便單元測試，不碰 DOM */

/** 預設選單寬度（PowerMenu）；需與 PowerMenu.module.scss 的 .powerMenu width 一致 */
export const MENU_WIDTH = 240;
/** 選單與錨點按鈕的間距 */
export const ANCHOR_GAP = 6;
/** 與視窗邊緣的最小留白 */
export const EDGE_MARGIN = 8;

/**
 * 依錨點按鈕的視窗座標算出選單的 fixed 位置。
 * 下方放不下且上方較寬裕時往上翻，最後再夾進視窗範圍避免溢出。
 *
 * @param {{top: number, bottom: number, left: number, right: number}} rect 錨點的 getBoundingClientRect()
 * @param {number} menuHeight 選單實際高度
 * @param {{width: number, height: number}} viewport 視窗尺寸
 * @param {"right"|"left"} align 選單與錨點對齊哪一側：按鈕選單右緣對齊，輸入框的建議選單左緣對齊
 */
export function computePosition(rect, menuHeight, viewport, menuWidth = MENU_WIDTH, align = "right") {
  const spaceBelow = viewport.height - rect.bottom - EDGE_MARGIN;
  const spaceAbove = rect.top - EDGE_MARGIN;
  const openUp = spaceBelow < menuHeight + ANCHOR_GAP && spaceAbove > spaceBelow;

  const rawTop  = openUp ? rect.top - ANCHOR_GAP - menuHeight : rect.bottom + ANCHOR_GAP;
  const rawLeft = align === "left" ? rect.left : rect.right - menuWidth;
  const maxTop  = viewport.height - menuHeight - EDGE_MARGIN;
  const maxLeft = viewport.width - menuWidth - EDGE_MARGIN;

  return {
    top:  Math.max(EDGE_MARGIN, Math.min(rawTop, maxTop)),
    left: Math.max(EDGE_MARGIN, Math.min(rawLeft, maxLeft)),
    openUp,
  };
}

/**
 * 給可以捲動的長清單用：放不下時不往上推（那會蓋住觸發鈕），而是把清單縮到剩下的空間、在清單內捲動。
 * 方向規則同 computePosition：下方放不下且上方比較寬裕才往上翻。
 *
 * @param {number} menuHeight 清單完整的高度（已夾在呼叫端給的上限內）
 * @returns {{top: number, left: number, openUp: boolean, maxHeight: number}}
 */
export function computeFittedPosition(rect, menuHeight, viewport, menuWidth = MENU_WIDTH, align = "right") {
  const spaceBelow = viewport.height - rect.bottom - ANCHOR_GAP - EDGE_MARGIN;
  const spaceAbove = rect.top - ANCHOR_GAP - EDGE_MARGIN;
  const openUp = spaceBelow < menuHeight && spaceAbove > spaceBelow;
  const maxHeight = Math.max(0, Math.min(menuHeight, openUp ? spaceAbove : spaceBelow));

  const rawLeft = align === "left" ? rect.left : rect.right - menuWidth;
  const maxLeft = viewport.width - menuWidth - EDGE_MARGIN;

  return {
    top: openUp ? rect.top - ANCHOR_GAP - maxHeight : rect.bottom + ANCHOR_GAP,
    left: Math.max(EDGE_MARGIN, Math.min(rawLeft, maxLeft)),
    openUp,
    maxHeight,
  };
}

/**
 * 側欄底部的選單（語言、帳號、背景任務）：貼著側欄外緣往右彈出，底緣對齊觸發鈕、往上長。
 * 側欄展開或收合都是同一個位置，也不會蓋住側欄裡的其他項目。
 * fit 為 true 時（可以捲動的長清單）放不下就縮高、在清單內捲動，否則整個往下推進視窗。
 *
 * @param {number} edgeRight 側欄外緣的 x 座標
 * @returns {{top: number, left: number, openUp: true, maxHeight?: number}}
 */
export function computeSidePosition(rect, edgeRight, menuHeight, viewport, menuWidth = MENU_WIDTH, fit = false) {
  const height = fit ? Math.max(0, Math.min(menuHeight, rect.bottom - EDGE_MARGIN)) : menuHeight;
  const maxTop = viewport.height - height - EDGE_MARGIN;
  const maxLeft = viewport.width - menuWidth - EDGE_MARGIN;

  return {
    top: Math.max(EDGE_MARGIN, Math.min(rect.bottom - height, maxTop)),
    left: Math.max(EDGE_MARGIN, Math.min(edgeRight + ANCHOR_GAP, maxLeft)),
    openUp: true,
    ...(fit ? { maxHeight: height } : {}),
  };
}

/** 錨點被捲出視窗外（選單只會卡在邊緣，該收起來） */
export function isAnchorOffscreen(rect, viewport) {
  return rect.bottom < 0 || rect.top > viewport.height;
}
