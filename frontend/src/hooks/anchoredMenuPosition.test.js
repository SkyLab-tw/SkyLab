import { describe, expect, test } from "vitest";
import {
  ANCHOR_GAP,
  EDGE_MARGIN,
  MENU_WIDTH,
  computeFittedPosition,
  computePosition,
  computeSidePosition,
  isAnchorOffscreen,
} from "./anchoredMenuPosition";

const VIEWPORT = { width: 1280, height: 800 };
const MENU_HEIGHT = 180;

/** 產生一個 30x30 錨點按鈕的 rect（模擬 ⋮ 按鈕） */
function anchorAt(top, right = 900) {
  return { top, bottom: top + 30, right };
}

describe("computePosition", () => {
  test("下方空間足夠時往下展開，貼在按鈕下緣", () => {
    const rect = anchorAt(200);
    const pos = computePosition(rect, MENU_HEIGHT, VIEWPORT);

    expect(pos.openUp).toBe(false);
    expect(pos.top).toBe(rect.bottom + ANCHOR_GAP);
  });

  test("下方放不下且上方較寬裕時往上翻，貼在按鈕上緣", () => {
    const rect = anchorAt(700); // bottom 730，下方只剩 70px
    const pos = computePosition(rect, MENU_HEIGHT, VIEWPORT);

    expect(pos.openUp).toBe(true);
    expect(pos.top).toBe(rect.top - ANCHOR_GAP - MENU_HEIGHT);
  });

  test("align 為 left 時左緣對齊錨點（輸入框的建議選單）", () => {
    const rect = { top: 200, bottom: 236, left: 300, right: 430 };
    const pos = computePosition(rect, MENU_HEIGHT, VIEWPORT, 280, "left");

    expect(pos.left).toBe(300);
  });

  test("align 為 left 且右側放不下時夾回視窗內", () => {
    const rect = { top: 200, bottom: 236, left: 1100, right: 1230 };
    const pos = computePosition(rect, MENU_HEIGHT, VIEWPORT, 280, "left");

    expect(pos.left).toBe(VIEWPORT.width - 280 - EDGE_MARGIN);
  });

  test("右緣對齊錨點按鈕", () => {
    const pos = computePosition(anchorAt(200, 900), MENU_HEIGHT, VIEWPORT);

    expect(pos.left).toBe(900 - MENU_WIDTH);
  });

  test("錨點靠左時不會被推出視窗左緣", () => {
    const pos = computePosition(anchorAt(200, 40), MENU_HEIGHT, VIEWPORT);

    expect(pos.left).toBe(EDGE_MARGIN);
  });

  test("錨點貼右時不會超出視窗右緣", () => {
    const pos = computePosition(anchorAt(200, VIEWPORT.width), MENU_HEIGHT, VIEWPORT);

    expect(pos.left + MENU_WIDTH).toBeLessThanOrEqual(VIEWPORT.width - EDGE_MARGIN);
  });

  test("上下都塞不下時夾在視窗內，不會被截斷", () => {
    const tallMenu = 700;
    const pos = computePosition(anchorAt(400), tallMenu, VIEWPORT);

    expect(pos.top).toBeGreaterThanOrEqual(EDGE_MARGIN);
    expect(pos.top + tallMenu).toBeLessThanOrEqual(VIEWPORT.height - EDGE_MARGIN);
  });

  test("錨點在最上方時即使下方不夠也不往上翻（上方更擠）", () => {
    const pos = computePosition(anchorAt(10), 760, VIEWPORT);

    expect(pos.openUp).toBe(false);
  });
});

describe("isAnchorOffscreen", () => {
  test("錨點在視窗內回傳 false", () => {
    expect(isAnchorOffscreen(anchorAt(200), VIEWPORT)).toBe(false);
  });

  test("錨點被往上捲出視窗回傳 true", () => {
    expect(isAnchorOffscreen({ top: -60, bottom: -30, right: 900 }, VIEWPORT)).toBe(true);
  });

  test("錨點還在視窗下方外回傳 true", () => {
    expect(isAnchorOffscreen(anchorAt(VIEWPORT.height + 20), VIEWPORT)).toBe(true);
  });
});

describe("computeFittedPosition", () => {
  /* 換週那種長清單：觸發鈕寬、清單最高 420 */
  const LIST_HEIGHT = 420;
  const wideAnchor = (top) => ({ top, bottom: top + 68, left: 400, right: 1300 });

  test("下方放得下就照完整高度往下展開", () => {
    const rect = wideAnchor(100);
    const pos = computeFittedPosition(rect, LIST_HEIGHT, VIEWPORT, 480, "left");

    expect(pos.openUp).toBe(false);
    expect(pos.top).toBe(rect.bottom + ANCHOR_GAP);
    expect(pos.maxHeight).toBe(LIST_HEIGHT);
    expect(pos.left).toBe(rect.left);
  });

  test("下方不夠但仍比上方寬：往下展開並縮到剩下的空間，不往上推蓋住觸發鈕", () => {
    const rect = wideAnchor(265); // bottom 333；732 高的視窗下方只剩 385，比上方的 251 寬
    const viewport = { width: 1440, height: 732 };
    const pos = computeFittedPosition(rect, LIST_HEIGHT, viewport, 480, "left");

    expect(pos.openUp).toBe(false);
    expect(pos.top).toBe(rect.bottom + ANCHOR_GAP);
    expect(pos.maxHeight).toBe(viewport.height - rect.bottom - ANCHOR_GAP - EDGE_MARGIN);
    expect(pos.top).toBeGreaterThanOrEqual(rect.bottom);
  });

  test("下方放不下且上方較寬裕時往上翻，清單底緣貼在觸發鈕上緣", () => {
    const rect = wideAnchor(600); // bottom 668，下方只剩 118
    const pos = computeFittedPosition(rect, LIST_HEIGHT, VIEWPORT, 480, "left");

    expect(pos.openUp).toBe(true);
    expect(pos.top + pos.maxHeight).toBe(rect.top - ANCHOR_GAP);
    expect(pos.maxHeight).toBe(LIST_HEIGHT);
  });

  test("短清單不會被撐高", () => {
    const pos = computeFittedPosition(wideAnchor(100), 120, VIEWPORT, 480, "left");
    expect(pos.maxHeight).toBe(120);
  });
});

describe("computeSidePosition", () => {
  const SIDEBAR_EDGE = 260;
  /** 側欄底部的觸發鈕：左右在側欄內、底緣在 bottom */
  const sidebarButton = (bottom) => ({ top: bottom - 40, bottom, left: 16, right: 244 });

  test("貼著側欄外緣往右彈出，底緣對齊觸發鈕", () => {
    const rect = sidebarButton(700);
    const pos = computeSidePosition(rect, SIDEBAR_EDGE, 130, VIEWPORT, 260);

    expect(pos.left).toBe(SIDEBAR_EDGE + ANCHOR_GAP);
    expect(pos.top + 130).toBe(rect.bottom);
    expect(pos.openUp).toBe(true);
    expect(pos.maxHeight).toBeUndefined();
  });

  test("比觸發鈕以上的空間還高：一般選單夾在視窗上緣，長清單改成縮高", () => {
    const rect = sidebarButton(300);

    expect(computeSidePosition(rect, SIDEBAR_EDGE, 400, VIEWPORT, 260).top).toBe(EDGE_MARGIN);

    const fitted = computeSidePosition(rect, SIDEBAR_EDGE, 400, VIEWPORT, 260, true);
    expect(fitted.maxHeight).toBe(rect.bottom - EDGE_MARGIN);
    expect(fitted.top + fitted.maxHeight).toBe(rect.bottom);
  });

  test("視窗太窄放不下時夾回視窗內", () => {
    const pos = computeSidePosition(sidebarButton(700), 300, 200, { width: 375, height: 812 }, 360);
    expect(pos.left).toBe(EDGE_MARGIN);
  });
});
