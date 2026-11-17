import { describe, it, expect } from "vitest";
import { LABEL_GAP, NODE_CLEARANCE, parsePath, placeEdgeLabel } from "./edgeLabelPlacement";

/* 一條水平直線：x 就是弧長 */
const STRAIGHT = "M0,0 C100,0 200,0 300,0";
const SIZE = { w: 60, h: 20 };

/* 回傳結果換成標籤實際佔的範圍 */
const rectOf = (p, size) => ({ x: p.x + p.ax * size.w, y: p.y + p.ay * size.h, w: size.w, h: size.h });
const inflate = (r) => ({
  x: r.x - NODE_CLEARANCE, y: r.y - NODE_CLEARANCE, w: r.w + NODE_CLEARANCE * 2, h: r.h + NODE_CLEARANCE * 2,
});
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe("parsePath", () => {
  it("解析 getBezierPath 的格式，解析不了回傳 null", () => {
    expect(parsePath("M1,2 C3,4 5,6 7,8")).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(parsePath("M1,2 L3,4")).toBeNull();
    expect(placeEdgeLabel("M1,2 L3,4", { nearTarget: false, size: SIZE })).toBeNull();
  });
});

describe("placeEdgeLabel", () => {
  it("沒有障礙時貼在主體旁 LABEL_GAP 處，往遠離它的方向展開", () => {
    const fromSource = placeEdgeLabel(STRAIGHT, { nearTarget: false, size: SIZE });
    expect(fromSource.x).toBeCloseTo(LABEL_GAP, 0);
    expect(fromSource.y).toBeCloseTo(0);
    expect([fromSource.ax, fromSource.ay]).toEqual([0, -0.5]);
    expect(fromSource.leader).toBeNull();

    /* 入站：主體是目標，從線尾往回量、標籤往左展開 */
    const fromTarget = placeEdgeLabel(STRAIGHT, { nearTarget: true, size: SIZE });
    expect(fromTarget.x).toBeCloseTo(300 - LABEL_GAP, 0);
    expect([fromTarget.ax, fromTarget.ay]).toEqual([-1, -0.5]);
  });

  it("同一對節點的多條線：標籤照 shift 錯開", () => {
    const placed = placeEdgeLabel(STRAIGHT, { nearTarget: false, size: SIZE, shift: { x: 0, y: 13 } });
    expect(placed.y).toBeCloseTo(13);
  });

  it("第三台機器擋在預設位置上：沿同一條線滑到空處，不拉引線", () => {
    const obstacles = [
      { x: -180, y: -34, w: 180, h: 68 }, // 來源
      { x: 60, y: -34, w: 100, h: 68 }, // 擋在線上的機器
      { x: 300, y: -34, w: 180, h: 68 }, // 目標
    ];
    const placed = placeEdgeLabel(STRAIGHT, { nearTarget: false, size: SIZE, obstacles });
    expect(placed.clear).toBe(true);
    expect(placed.leader).toBeNull();
    expect(placed.y).toBeCloseTo(0);
    const rect = rectOf(placed, SIZE);
    for (const node of obstacles) expect(overlaps(rect, inflate(node))).toBe(false);
  });

  it("兩台緊貼、線短到放不下：移到旁邊空處並拉引線指回線上", () => {
    /* 對應實際案例：nginx 右緣跟 mariadb 左緣只隔 6px，mariadb 低一點 */
    const nginx = { x: 0, y: 0, w: 180, h: 68 };
    const mariadb = { x: 186, y: 38, w: 180, h: 68 };
    const size = { w: 85, h: 20 };
    const placed = placeEdgeLabel("M180,34 C183,34 183,72 186,72", {
      nearTarget: false, size, obstacles: [nginx, mariadb],
    });
    expect(placed.clear).toBe(true);
    const rect = rectOf(placed, size);
    expect(overlaps(rect, inflate(nginx))).toBe(false);
    expect(overlaps(rect, inflate(mariadb))).toBe(false);
    /* 引線從線上的點接到標籤邊緣 */
    expect(placed.leader).not.toBeNull();
    expect(placed.leader.y1).toBeGreaterThan(34);
    expect(placed.leader.y1).toBeLessThan(72);
    expect(placed.leader.x2).toBeGreaterThanOrEqual(rect.x);
    expect(placed.leader.x2).toBeLessThanOrEqual(rect.x + rect.w);
    expect(placed.leader.y2).toBeGreaterThanOrEqual(rect.y);
    expect(placed.leader.y2).toBeLessThanOrEqual(rect.y + rect.h);
  });

  it("前面已排好的標籤也要避開，並回傳自己佔的範圍給後面的避", () => {
    const first = placeEdgeLabel(STRAIGHT, { nearTarget: false, size: SIZE });
    expect(first.rect).toEqual({ x: first.x, y: first.y - SIZE.h / 2, w: SIZE.w, h: SIZE.h });
    const second = placeEdgeLabel(STRAIGHT, { nearTarget: false, size: SIZE, labels: [first.rect] });
    expect(second.clear).toBe(true);
    expect(overlaps(second.rect, first.rect)).toBe(false);
  });

  it("整片都被佔滿：留在預設點並回報沒避開", () => {
    const placed = placeEdgeLabel(STRAIGHT, {
      nearTarget: false, size: SIZE, obstacles: [{ x: -1000, y: -1000, w: 3000, h: 3000 }],
    });
    expect(placed.clear).toBe(false);
    expect(placed.leader).toBeNull();
    expect(placed.x).toBeCloseTo(LABEL_GAP, 0);
  });
});
