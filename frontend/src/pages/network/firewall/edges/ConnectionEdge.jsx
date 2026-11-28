import { useLayoutEffect, useMemo, useState } from "react";
import { EdgeLabelRenderer, getBezierPath, useStore } from "@xyflow/react";
import { useTranslation } from "react-i18next";
import styles from "../FirewallPage.module.scss";
import { parsePath, placeEdgeLabel } from "../utils/edgeLabelPlacement";
import { useEarlierLabelRects, usePublishLabelRect } from "./labelRegistry";

/* 同一對節點之間的多條線，彼此錯開的量。控制點偏移，端點不動 */
const LANE_GAP = 56;
/* 標籤在端點附近時線才剛分岔，額外再錯開一點才不會疊住 */
const LANE_LABEL_GAP = 26;
/* 標籤量到實際尺寸前的估計（.edgeLabel：11px 字、左右內距 8、最寬 170） */
const estimateLabelSize = (text) => ({ w: Math.min(170, String(text).length * 8 + 18), h: 20 });

/**
 * 單位法線。方向統一朝右半平面，否則入站與出站因為起訖點互換，
 * 算出來的法線相反，各自往「自己的左邊」偏移後又會疊回同一條線上。
 */
function unitNormal([x0, y0, , , , , x3, y3]) {
  const dx = x3 - x0;
  const dy = y3 - y0;
  const len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len;
  let ny = dx / len;
  if (nx < -1e-6 || (Math.abs(nx) <= 1e-6 && ny < 0)) {
    nx = -nx;
    ny = -ny;
  }
  return { nx, ny };
}

/** 只推開控制點，端點仍固定在 handle 上，線才不會脫離節點 */
function spreadPath([x0, y0, x1, y1, x2, y2, x3, y3], { nx, ny }, offset) {
  const ox = nx * offset;
  const oy = ny * offset;
  return `M${x0},${y0} C${x1 + ox},${y1 + oy} ${x2 + ox},${y2 + oy} ${x3},${y3}`;
}

/* 標籤要避開的節點：畫布上看得到的卡片（絕對座標）。
   群組框（有子節點的父節點）本身是背景，標籤放在框裡沒關係，不算 */
function selectNodeRects(state) {
  const rects = [];
  for (const node of state.nodeLookup.values()) {
    if (node.hidden || state.parentLookup.has(node.id)) continue;
    const w = node.measured?.width;
    const h = node.measured?.height;
    if (!w || !h) continue;
    const { x, y } = node.internals.positionAbsolute;
    rects.push({ x, y, w, h });
  }
  return rects;
}

/* 平移縮放畫布也會觸發 store 更新：節點沒動就回同一份，標籤不必重算 */
function sameRects(a, b) {
  return a.length === b.length
    && a.every((r, i) => r.x === b[i].x && r.y === b[i].y && r.w === b[i].w && r.h === b[i].h);
}

/* ─── 邊動畫 keyframes（注入 head，避免 React 19 的 <style> 提升行為破壞 SVG 結構） ── */
if (!document.getElementById("flow-fwd-kf")) {
  const s = document.createElement("style");
  s.id = "flow-fwd-kf";
  s.textContent = `@keyframes flow-fwd{from{stroke-dashoffset:12}to{stroke-dashoffset:0}}`;
  document.head.appendChild(s);
}

export default function ConnectionEdge(props) {
  const {
    id, sourceX, sourceY, targetX, targetY,
    sourcePosition, targetPosition, data,
  } = props;

  const { t } = useTranslation("network");
  const [hovered, setHovered] = useState(false);
  /* 只有滑鼠、觸控筆才算滑過：iOS 點下去時若 hover 讓隱藏的標籤浮出來，第一下只會被當成 hover，
     要點兩下才選得到這條線（同 reveal-on-hover 的規則） */
  const hoverHandlers = {
    onPointerEnter: (event) => {
      if (event.pointerType !== "touch") setHovered(true);
    },
    onPointerLeave: () => setHovered(false),
  };
  const [basePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });

  /* 同一對節點之間的線各走一側：入站與出站的端點完全相同，
     不錯開就會疊成一條，看不出有兩條規則也點不到下面那條 */
  const laneCount = data?.laneCount ?? 1;
  const lane = laneCount > 1 ? (data?.laneIndex ?? 0) - (laneCount - 1) / 2 : 0;
  const parsed = lane ? parsePath(basePath) : null;
  const normal = parsed ? unitNormal(parsed) : null;
  const edgePath = parsed && normal
    ? spreadPath(parsed, normal, lane * LANE_GAP)
    : basePath;

  const edge       = data?.edge ?? {};
  const isInbound  = edge.source_vmid === null;
  const isOutbound = edge.target_vmid === null;
  const isBidirectional = edge.direction === "bidirectional";
  const isSelected = Boolean(data?.selected);
  // 入站亮藍 / 出站綠 / 內部灰，走主題語意色；hover 用 color-mix 提亮，深淺色模式都跟著換
  const baseColor = isInbound
    ? "var(--color-flow-inbound)"
    : isOutbound
    ? "var(--color-success)"
    : "var(--color-status-neutral)";
  const color = hovered || isSelected
    ? `color-mix(in srgb, ${baseColor} 70%, white)`
    : baseColor;

  /* 上網線（出站、不限 port）是常態，每條都標「不限通訊埠」只是雜訊：常駐標籤略過，滑過或選取仍顯示 */
  const routineOutbound = isOutbound && !data?.label && !(data?.aggregateCount > 1);
  const showLabel = hovered || isSelected || (data?.showLabel && !routineOutbound);
  /* 箭頭 marker 必須是全域唯一 id；edge id 已含來源與目標，直接沿用 */
  const markerId = `arrow-${id}`;
  const markerRef = `url(#${markerId})`;
  const strokeWidth = isSelected ? 3 : hovered ? 2.5 : 1.8;
  /* 唯讀檢視（資源詳情的迷你拓撲）沒有細節面板可開，就不要裝成可點 */
  const clickable = Boolean(data?.onSelect);
  const cursor = clickable ? "pointer" : "default";
  const select = () => data?.onSelect?.(edge, id);
  /* 不限 port 的連線（出站上網等）沒有可列的埠，仍要講清楚它開了什麼 */
  /* 收合群組合併出來的線：講條數，點下去展開群組 */
  const label = data?.aggregateCount > 1
    ? t("ConnectionEdge.aggregate", { count: data.aggregateCount })
    : data?.label || t("ConnectionEdge.allPorts");

  /* 標籤尺寸：先用估計值排，畫出來量到實際寬高再重排一次。
     標籤走 EdgeLabelRenderer 的 portal，第一次 render 時容器常常還沒好、元素不存在，
     所以用 callback ref 等元素真的掛上才量；字型載入、文字改變造成的尺寸變化交給 ResizeObserver。
     offsetWidth 不受畫布縮放（transform）影響，量到的就是畫布座標的尺寸 */
  const [labelEl, setLabelEl] = useState(null);
  const [measured, setMeasured] = useState(null);
  useLayoutEffect(() => {
    if (!labelEl) return undefined;
    const measure = () => {
      const w = labelEl.offsetWidth;
      const h = labelEl.offsetHeight;
      if (!w || !h) return;
      setMeasured((prev) => (prev?.w === w && prev?.h === h ? prev : { w, h }));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(labelEl);
    return () => observer.disconnect();
  }, [labelEl, label]);
  const { w: labelW, h: labelH } = measured ?? estimateLabelSize(label);

  /* 機器拖得太近或剛好擋在線上時，標籤會被節點蓋掉：避開所有節點與前面已排好的標籤找空位
     （見 edgeLabelPlacement、labelRegistry） */
  const nodeRects = useStore(selectNodeRects, sameRects);
  const rank = useStore((state) => state.edges.findIndex((e) => e.id === id));
  /* 只有常駐的標籤佔位、依順序排；滑過、選取才浮出的不推開別人，但要避開所有常駐標籤 */
  const persistentLabel = Boolean(data?.showLabel) && !routineOutbound;
  const earlierLabels = useEarlierLabelRects(id, persistentLabel ? rank : Infinity);
  /* 入站的主體是目標 VM，出站與內部互通的主體是來源 VM；
     同一對節點的多條線在標籤附近才剛分岔，再往外錯開一段才分得開 */
  const laneShiftX = normal ? normal.nx * lane * LANE_LABEL_GAP : 0;
  const laneShiftY = normal ? normal.ny * lane * LANE_LABEL_GAP : 0;
  const placement = useMemo(
    () => placeEdgeLabel(edgePath, {
      nearTarget: isInbound,
      size: { w: labelW, h: labelH },
      obstacles: nodeRects,
      labels: earlierLabels,
      shift: { x: laneShiftX, y: laneShiftY },
    }) ?? {
      x: labelX, y: labelY, ax: -0.5, ay: -0.5, leader: null,
      rect: { x: labelX - labelW / 2, y: labelY - labelH / 2, w: labelW, h: labelH },
    },
    [edgePath, isInbound, labelW, labelH, nodeRects, earlierLabels, laneShiftX, laneShiftY, labelX, labelY],
  );
  const leader = placement.leader;
  usePublishLabelRect(id, rank, persistentLabel ? placement.rect : null);

  return (
    <g>
      {/* 箭頭：單向只有終點，雙向兩端都有（orient 讓起點的箭頭自動反向） */}
      <defs>
        <marker
          id={markerId}
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          markerUnits="userSpaceOnUse"
          orient="auto-start-reverse"
        >
          <path d="M0,1 L9,5 L0,9 z" fill={color} />
        </marker>
      </defs>

      {/* 透明寬路徑：hover 偵測與點擊區 */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        style={{ cursor }}
        onClick={select}
        {...hoverHandlers}
      />

      {/* 主流向路徑（動畫虛線） */}
      <path
        id={id}
        d={edgePath}
        className="react-flow__edge-path"
        markerEnd={markerRef}
        markerStart={isBidirectional ? markerRef : undefined}
        style={{
          fill: "none",
          stroke: color,
          strokeWidth,
          strokeDasharray: "8 4",
          animation: "flow-fwd 1.2s linear infinite",
          opacity: 0.9,
          transition: "stroke 0.2s",
          cursor,
        }}
        onClick={select}
      />

      {/* 線上沒空位、標籤移到旁邊時，拉一條細線指回這條線，才看得出標籤是誰的 */}
      {leader && (
        <line
          x1={leader.x1}
          y1={leader.y1}
          x2={leader.x2}
          y2={leader.y2}
          stroke={color}
          strokeWidth={1.2}
          strokeDasharray="2 3"
          style={{ opacity: showLabel ? 0.8 : 0, transition: "opacity 0.15s", pointerEvents: "none" }}
        />
      )}

      <EdgeLabelRenderer>
        <div
          ref={setLabelEl}
          className={`${styles.edgeLabelWrap} nodrag nopan`}
          style={{
            position: "absolute",
            transform: `translate(${placement.ax * 100}%, ${placement.ay * 100}%) translate(${placement.x}px,${placement.y}px)`,
            /* 疊在節點上層：位置已避開節點，萬一真的擠到沒空位也只是蓋住節點一角，不會整個被節點吃掉 */
            zIndex: 1,
            pointerEvents: showLabel ? "all" : "none",
            opacity: showLabel ? 1 : 0,
            transition: "opacity 0.15s",
          }}
          {...hoverHandlers}
        >
          <button
            type="button"
            className={`${styles.edgeLabel} ${isSelected ? styles.edgeLabelActive : ""}`}
            style={{ color, cursor }}
            onClick={select}
            title={label}
          >
            {label}
          </button>
        </div>
      </EdgeLabelRenderer>
    </g>
  );
}
