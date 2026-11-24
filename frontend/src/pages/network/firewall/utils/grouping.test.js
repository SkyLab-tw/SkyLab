/**
 * grouping.test.js
 * 拓撲分組、收合、篩選：
 *   - 班級機依班級、其他依機器類型分組，摘要（台數／開機／對外開放）正確
 *   - 收合後群組內往外的線併成一條、記條數；群組內部的線不畫
 *   - 搜尋時命中所在的群組強制展開；篩選回報看得到幾台
 *   - 不分組時只拿掉被篩掉的機器與它們的線
 */

import { describe, expect, test, vi } from "vitest";
import { GATEWAY_KEY, buildFlow } from "./buildFlow";
import {
  applyGroupRefits,
  applyView,
  buildGroups,
  defaultCollapsed,
  groupKeyOf,
  groupKeyOfId,
  groupNodeId,
  listGroupKeys,
  refitGroup,
  vmidsWithRules,
  COLLAPSE_THRESHOLD,
} from "./grouping";

const vm = (vmid, extra = {}) => ({
  vmid,
  name: `vm-${vmid}`,
  node_type: "vm",
  status: "running",
  ip_address: `10.0.0.${vmid}`,
  machine_kind: "personal",
  ...extra,
});

const TOPOLOGY = {
  nodes: [
    { vmid: null, name: "gateway", node_type: "gateway" },
    vm(101, { machine_kind: "teaching_class", class_relation: "teacher", teaching_class_name: "資二甲" }),
    vm(102, { machine_kind: "teaching_class", class_relation: "teacher", teaching_class_name: "資二甲", status: "stopped" }),
    vm(103, { machine_kind: "teaching_class", class_relation: "teacher", teaching_class_name: "資二甲" }),
    vm(201),
    vm(202),
  ],
  edges: [
    { source_vmid: null, target_vmid: 101, ports: [{ port: 80, protocol: "tcp" }] }, // 對外開放
    { source_vmid: 102, target_vmid: null, ports: [] }, // 上網線
    { source_vmid: 103, target_vmid: null, ports: [] }, // 上網線
    { source_vmid: 101, target_vmid: 102, ports: [{ port: 22, protocol: "tcp" }] }, // 同班內部
    { source_vmid: 201, target_vmid: 101, ports: [{ port: 5432, protocol: "tcp" }] }, // 跨群組
  ],
};

const flow = () => buildFlow(TOPOLOGY, { showLabel: true, showInternet: true });
const CLASS_KEY = "class:資二甲";
const PERSONAL_KEY = "kind:personal";

describe("分組", () => {
  test("班級機依班級，其他依機器類型", () => {
    expect(groupKeyOf(TOPOLOGY.nodes[1])).toBe(CLASS_KEY);
    expect(groupKeyOf(TOPOLOGY.nodes[4])).toBe(PERSONAL_KEY);
    expect(listGroupKeys(TOPOLOGY.nodes)).toEqual([CLASS_KEY, PERSONAL_KEY]);
  });

  test("摘要：台數、開機數、對外開放數", () => {
    const groups = buildGroups(flow().nodes.filter((n) => n.type === "vm"));
    const cls = groups.find((g) => g.key === CLASS_KEY);
    expect(cls).toMatchObject({ total: 3, running: 2, exposed: 1 });
  });

  test("有規則＝扣掉上網線後還有連線", () => {
    expect([...vmidsWithRules(TOPOLOGY.edges)].sort()).toEqual(["101", "102", "201"]);
  });

  test("預設收合：機器多且沒有對外開放才收", () => {
    expect(defaultCollapsed({ exposed: 0 }, COLLAPSE_THRESHOLD + 1)).toBe(true);
    expect(defaultCollapsed({ exposed: 2 }, COLLAPSE_THRESHOLD + 1)).toBe(false);
    expect(defaultCollapsed({ exposed: 0 }, COLLAPSE_THRESHOLD)).toBe(false);
  });
});

describe("applyView 分組模式", () => {
  test("展開：群組框在子節點前面，子節點掛在群組底下", () => {
    const view = applyView(flow(), TOPOLOGY.edges, { grouped: true });
    const groupIndex = view.nodes.findIndex((n) => n.id === groupNodeId(CLASS_KEY));
    const childIndex = view.nodes.findIndex((n) => n.id === "101");
    expect(groupIndex).toBeGreaterThanOrEqual(0);
    expect(childIndex).toBeGreaterThan(groupIndex);
    /* 框內機器可拖、可拖出框外（框跟著長大），不再鎖在格子裡 */
    expect(view.nodes[childIndex]).toMatchObject({ parentId: groupNodeId(CLASS_KEY), expandParent: true });
    expect(view.nodes[childIndex].draggable).not.toBe(false);
    expect(view.nodes[childIndex].extent).toBeUndefined();
    expect(view.nodes.some((n) => n.id === GATEWAY_KEY)).toBe(true);
  });

  test("收合：往外的線改接群組並記條數，群組內部的線不畫", () => {
    const onExpandGroup = vi.fn();
    const view = applyView(flow(), TOPOLOGY.edges, {
      grouped: true,
      isCollapsed: (g) => g.key === CLASS_KEY,
      onExpandGroup,
    });
    const groupId = groupNodeId(CLASS_KEY);
    expect(view.nodes.some((n) => n.id === "101")).toBe(false);
    /* 102、103 → 網際網路的兩條上網線併成一條 */
    const outbound = view.edges.find((e) => e.source === groupId && e.target === GATEWAY_KEY);
    expect(outbound.data.aggregateCount).toBe(2);
    /* 101 → 102 是同一個群組內部，不畫 */
    expect(view.edges.some((e) => e.source === groupId && e.target === groupId)).toBe(false);
    /* 跨群組的 201 → 101 改接到群組 */
    expect(view.edges.some((e) => e.source === "201" && e.target === groupId)).toBe(true);
    /* 摘要卡的規則數：對外開放→101、101→102、201→101 共三條（上網線不算） */
    expect(view.nodes.find((n) => n.id === groupId).data.rules).toBe(3);
    /* 點合併線＝展開群組 */
    outbound.data.onSelect();
    expect(onExpandGroup).toHaveBeenCalledWith(CLASS_KEY);
  });

  test("搜尋時命中所在的群組強制展開", () => {
    const view = applyView(flow(), TOPOLOGY.edges, {
      grouped: true,
      isCollapsed: () => true,
      filter: { query: "vm-102" },
    });
    expect(view.visibleVms).toBe(1);
    expect(view.nodes.some((n) => n.id === "102")).toBe(true);
    expect(view.nodes.find((n) => n.id === groupNodeId(CLASS_KEY)).data.collapsed).toBe(false);
  });

  test("只有一台的群組不畫框，那台直接排在堆疊裡；篩選後只剩一台的仍保留框", () => {
    const topology = {
      ...TOPOLOGY,
      nodes: [...TOPOLOGY.nodes, vm(301, { machine_kind: "teaching_class", class_relation: "teacher", teaching_class_name: "獨班" })],
    };
    const view = applyView(buildFlow(topology, { showLabel: true, showInternet: true }), topology.edges, {
      grouped: true,
      isCollapsed: () => true,
    });
    expect(view.nodes.some((n) => n.id === groupNodeId("class:獨班"))).toBe(false);
    expect(view.nodes.find((n) => n.id === "301").draggable).not.toBe(false);
    expect(view.nodes.find((n) => n.id === "301").parentId).toBeUndefined();
    /* 拖過的單機照存的位置放（存在 groups：那台就是這個群組） */
    const moved = applyView(buildFlow(topology, { showLabel: true, showInternet: true }), topology.edges, {
      grouped: true,
      isCollapsed: () => true,
      positions: { groups: { "class:獨班": { x: 700, y: 30 } } },
    });
    expect(moved.nodes.find((n) => n.id === "301").position).toEqual({ x: 700, y: 30 });
    /* 資二甲有三台，搜尋只命中一台：框還在，才看得出它是哪一班的 */
    const searched = applyView(flow(), TOPOLOGY.edges, { grouped: true, filter: { query: "vm-102" } });
    expect(searched.nodes.some((n) => n.id === groupNodeId(CLASS_KEY))).toBe(true);
  });

  test("拖曳過的群組位置優先於自動排列", () => {
    const view = applyView(flow(), TOPOLOGY.edges, {
      grouped: true,
      positions: { groups: { [PERSONAL_KEY]: { x: 999, y: 888 } } },
    });
    expect(view.nodes.find((n) => n.id === groupNodeId(PERSONAL_KEY)).position).toEqual({ x: 999, y: 888 });
  });
});

describe("群組框內的機器拖曳", () => {
  const frameOf = (view) => view.nodes.find((n) => n.id === groupNodeId(CLASS_KEY));
  const at = (view, id) => view.nodes.find((n) => n.id === id).position;
  const grouped = (positions) => applyView(flow(), TOPOLOGY.edges, { grouped: true, positions });

  test("沒拖過：框內格狀排列，框的大小跟原本一樣", () => {
    const view = grouped({});
    expect([at(view, "101"), at(view, "102"), at(view, "103")]).toEqual([
      { x: 16, y: 58 }, { x: 226, y: 58 }, { x: 436, y: 58 },
    ]);
    expect(frameOf(view).style).toEqual({ width: 662, height: 162 });
  });

  test("拖過的機器照存的位置放，沒拖過的補進沒被佔走的格子", () => {
    const view = grouped({ members: { [CLASS_KEY]: { 102: { x: 16, y: 58 } } } });
    expect(at(view, "102")).toEqual({ x: 16, y: 58 });
    expect(at(view, "101")).toEqual({ x: 226, y: 58 });
    expect(at(view, "103")).toEqual({ x: 436, y: 58 });
  });

  test("框貼著機器外圍：拖遠了框跟著長大", () => {
    const view = grouped({ members: { [CLASS_KEY]: {
      101: { x: 16, y: 58 }, 102: { x: 16, y: 300 }, 103: { x: 500, y: 58 },
    } } });
    /* 右邊留 46、下面留 36（跟格狀版面最後一欄／列外的留白一樣） */
    expect(frameOf(view).style).toEqual({ width: 500 + 180 + 46, height: 300 + 68 + 36 });
  });

  test("拖到框的左上方：框往左上長，機器在畫面上不動", () => {
    const view = grouped({
      groups: { [CLASS_KEY]: { x: 100, y: 100 } },
      members: { [CLASS_KEY]: { 101: { x: -84, y: 18 }, 102: { x: 16, y: 58 }, 103: { x: 226, y: 58 } } },
    });
    const frame = frameOf(view);
    expect(frame.position).toEqual({ x: 0, y: 60 });
    expect(frame.data.memberShift).toEqual({ x: -100, y: -40 });
    /* 畫布上的絕對位置＝框＋相對位置，跟存的一樣 */
    expect(at(view, "101")).toEqual({ x: 16, y: 58 });
    expect(at(view, "102")).toEqual({ x: 116, y: 98 });
  });
});

describe("拖完框內機器後重新貼合群組框", () => {
  const frame = (extra = {}) => ({
    id: "g", type: "vmGroup", position: { x: 100, y: 100 },
    data: { groupKey: CLASS_KEY, memberShift: { x: 0, y: 0 } }, style: { width: 662, height: 162 }, ...extra,
  });
  const child = (id, x, y) => ({ id, type: "vm", parentId: "g", position: { x, y } });

  test("拖到框外：框長大、位置不變；框內每台的位置都回報（沒拖的也釘住）", () => {
    const refit = refitGroup([frame(), child("a", 16, 58), child("b", 300, 200)], "g");
    expect(refit).toMatchObject({ id: "g", groupKey: CLASS_KEY, position: { x: 100, y: 100 }, width: 526, height: 304 });
    expect(Object.fromEntries(refit.members)).toEqual({ a: { x: 16, y: 58 }, b: { x: 300, y: 200 } });
  });

  test("拖到框的左上方：框往左上挪，機器換算成新框的相對位置", () => {
    const refit = refitGroup([frame({ data: { groupKey: CLASS_KEY, memberShift: { x: 5, y: 0 } } }),
      child("a", 16, 58), child("b", -50, 10)], "g");
    expect(refit.position).toEqual({ x: 34, y: 52 });
    expect(Object.fromEntries(refit.members)).toEqual({ a: { x: 82, y: 106 }, b: { x: 16, y: 58 } });
    /* 篩掉沒畫出來的機器：存的位置要減掉畫出來時的位移（memberShift）加上這次的 */
    expect(refit.savedOffset).toEqual({ x: -61, y: -48 });
  });

  test("套到畫布：框的位置、大小（含 expandParent 寫進去的 width／height）與機器位置一起換", () => {
    const nodes = [frame({ width: 900, height: 500 }), child("a", 16, 58), child("b", 300, 200), { id: "other", position: { x: 1, y: 1 } }];
    const next = applyGroupRefits(nodes, [refitGroup(nodes, "g")]);
    expect(next[0]).toMatchObject({ width: 526, height: 304, style: { width: 526, height: 304 } });
    expect(next[3]).toBe(nodes[3]);
    expect(applyGroupRefits(nodes, [])).toBe(nodes);
  });
});

describe("applyView 不分組", () => {
  test("只看對外開放：只留有暴露面的機器與它們的線，並回報台數", () => {
    const view = applyView(flow(), TOPOLOGY.edges, { filter: { onlyExposed: true } });
    expect(view.totalVms).toBe(5);
    /* 只有 101 被網際網路開放 80 port */
    expect(view.visibleVms).toBe(1);
    expect(view.nodes.map((n) => n.id).sort()).toEqual(["101", GATEWAY_KEY].sort());
    expect(view.edges.some((e) => e.source === "103" || e.source === "201")).toBe(false);
  });

  test("篩光了：網際網路節點也不畫，畫布留給空狀態", () => {
    const view = applyView(flow(), TOPOLOGY.edges, { filter: { query: "沒有這台" } });
    expect(view.visibleVms).toBe(0);
    expect(view.nodes).toEqual([]);
    expect(view.edges).toEqual([]);
  });

  test("群組篩選只留該群組", () => {
    const view = applyView(flow(), TOPOLOGY.edges, { filter: { groupKey: PERSONAL_KEY } });
    expect(view.nodes.filter((n) => n.type === "vm").map((n) => n.id).sort()).toEqual(["201", "202"]);
  });
});

describe("群組 id 與搜尋中的收合", () => {
  test("群組 id 不含空白、引號、括號（會進 marker 的 url(#…)），且能還原成 key", () => {
    const key = "class:Network Security (A) 'B'";
    const id = groupNodeId(key);
    expect(id).not.toMatch(/[\s"'()]/);
    expect(groupKeyOfId(id)).toBe(key);
  });

  test("班級名稱含空白：合併邊點下去展開的仍是原本的群組 key", () => {
    const name = "網路 安全";
    const topology = {
      nodes: [
        { vmid: null, name: "gateway", node_type: "gateway" },
        vm(401, { machine_kind: "teaching_class", class_relation: "teacher", teaching_class_name: name }),
        vm(402, { machine_kind: "teaching_class", class_relation: "teacher", teaching_class_name: name }),
      ],
      edges: [{ source_vmid: null, target_vmid: 401, ports: [{ port: 80, protocol: "tcp" }] }],
    };
    const onExpandGroup = vi.fn();
    const view = applyView(buildFlow(topology, { showLabel: true, showInternet: true }), topology.edges, {
      grouped: true,
      isCollapsed: () => true,
      onExpandGroup,
    });
    const agg = view.edges.find((e) => e.data.aggregateCount >= 1);
    expect(agg.id).not.toMatch(/[\s"'()]/);
    agg.data.onSelect();
    expect(onExpandGroup).toHaveBeenCalledWith(`class:${name}`);
  });

  test("搜尋中群組被強制展開，標題不給切收合；沒搜尋時照常", () => {
    const onToggleGroup = vi.fn();
    const searched = applyView(flow(), TOPOLOGY.edges, { grouped: true, filter: { query: "vm-102" }, onToggleGroup });
    expect(searched.nodes.find((n) => n.id === groupNodeId(CLASS_KEY)).data.onToggle).toBeUndefined();
    const plain = applyView(flow(), TOPOLOGY.edges, { grouped: true, onToggleGroup });
    expect(plain.nodes.find((n) => n.id === groupNodeId(CLASS_KEY)).data.onToggle).toBe(onToggleGroup);
  });
});
