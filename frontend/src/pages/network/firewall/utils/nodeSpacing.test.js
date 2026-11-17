import { describe, it, expect } from "vitest";
import { NODE_GAP, applyMoves, nearestFreeSpot, settleDraggedNodes, settleDroppedNodes } from "./nodeSpacing";

const vm = (id, x, y, extra = {}) => ({
  id, type: "vm", position: { x, y }, measured: { width: 180, height: 68 }, ...extra,
});

/* 兩個範圍之間是否至少隔 gap */
const spaced = (a, b, gap = NODE_GAP) => !(
  a.x < b.x + b.w + gap && b.x - gap < a.x + a.w
  && a.y < b.y + b.h + gap && b.y - gap < a.y + a.h
);

describe("settleDroppedNodes", () => {
  it("放下的位置本來就夠空：不挪", () => {
    const nodes = [vm("a", 0, 0), vm("b", 300, 0)];
    expect(settleDroppedNodes(nodes, ["b"]).size).toBe(0);
  });

  it("緊貼在旁邊（只隔 6px）：往外推到剛好隔 NODE_GAP，另一軸不動", () => {
    const nodes = [vm("nginx", 0, 0), vm("mariadb", 186, 38)];
    const moves = settleDroppedNodes(nodes, ["mariadb"]);
    expect(moves.get("mariadb")).toEqual({ x: 180 + NODE_GAP, y: 38 });
    expect(moves.has("nginx")).toBe(false);
  });

  it("整張疊上去：挪到最近的一側", () => {
    const nodes = [vm("a", 0, 0), vm("b", 0, 0)];
    const spot = settleDroppedNodes(nodes, ["b"]).get("b");
    expect(spot.x).toBe(0);
    expect(Math.abs(spot.y)).toBe(68 + NODE_GAP);
  });

  it("推開時不會推進第三台：找離放下位置最近、跟每台都隔得開的地方", () => {
    const a = vm("a", 0, 0);
    const b = vm("b", 0, 68 + NODE_GAP);
    const dropped = vm("c", 10, 40);
    const spot = settleDroppedNodes([a, b, dropped], ["c"]).get("c");
    expect(spot).toEqual({ x: 10, y: -68 - NODE_GAP });
    const rect = { ...spot, w: 180, h: 68 };
    expect(spaced(rect, { x: 0, y: 0, w: 180, h: 68 })).toBe(true);
    expect(spaced(rect, { x: 0, y: 68 + NODE_GAP, w: 180, h: 68 })).toBe(true);
  });

  it("只比最上層的節點：群組框裡的機器（相對座標）與藏起來的節點不算", () => {
    const nodes = [
      vm("group", 0, 0, { type: "vmGroup", measured: { width: 440, height: 160 } }),
      vm("child", 500, 0, { parentId: "group" }),
      vm("hidden", 500, 0, { hidden: true }),
      vm("dropped", 500, 0),
    ];
    expect(settleDroppedNodes(nodes, ["dropped"]).size).toBe(0);
  });

  it("movable 排除的節點（群組框）照放不推，但仍是其他節點的障礙", () => {
    const group = vm("group", 0, 0, { type: "vmGroup", measured: { width: 440, height: 160 } });
    const below = vm("below", 0, 200);
    const gateway = vm("gateway", 450, 0, { type: "gateway", measured: { width: 90, height: 90 } });
    const nodes = [{ ...group, position: { x: 0, y: 60 } }, below, gateway];
    const moves = settleDroppedNodes(nodes, ["group", "gateway"], { movable: (node) => node.type !== "vmGroup" });
    expect(moves.has("group")).toBe(false);
    /* 網際網路節點仍要避開剛放下的群組框 */
    expect(moves.get("gateway")).toEqual({ x: 440 + NODE_GAP, y: 0 });
  });

  it("一次放下好幾台：逐台安置，彼此也隔得開", () => {
    const nodes = [vm("a", 0, 0), vm("b", 10, 10), vm("c", 20, 20)];
    const moves = settleDroppedNodes(nodes, ["b", "c"]);
    const at = (id) => ({ ...(moves.get(id) ?? nodes.find((n) => n.id === id).position), w: 180, h: 68 });
    expect(spaced(at("a"), at("b"))).toBe(true);
    expect(spaced(at("a"), at("c"))).toBe(true);
    expect(spaced(at("b"), at("c"))).toBe(true);
  });

  it("拖曳結束：以拖曳給的最終位置為準（畫布 state 還慢一拍），回傳挪好的拖曳節點", () => {
    const canvas = [vm("nginx", 0, 0), vm("mariadb", 600, 300)]; // 畫布還停在拖之前
    const { moves, dragged } = settleDraggedNodes(canvas, [vm("mariadb", 186, 38)]);
    expect(dragged).toHaveLength(1);
    expect(dragged[0].position).toEqual({ x: 180 + NODE_GAP, y: 38 });
    expect(applyMoves(canvas, moves)[1].position).toEqual({ x: 180 + NODE_GAP, y: 38 });
    /* 沒有要挪的：原陣列照回 */
    expect(applyMoves(canvas, new Map())).toBe(canvas);
  });

  it("量到尺寸前用 style 寬高（群組框）或預設卡片大小", () => {
    expect(nearestFreeSpot({ x: 0, y: 0, w: 10, h: 10 }, [])).toBeNull();
    const nodes = [
      { id: "g", position: { x: 0, y: 0 }, style: { width: 400, height: 200 } },
      { id: "d", position: { x: 390, y: 0 } },
    ];
    expect(settleDroppedNodes(nodes, ["d"]).get("d")).toEqual({ x: 400 + NODE_GAP, y: 0 });
  });
});
