/**
 * 放下節點時保持最小間距（純函式，不碰 React）。
 *
 * 機器可以自由拖。拖得太近時，卡片外緣的徽章（來源、對外開放數）會互相壓到，
 * 兩台之間的連線也短到放不下標籤；整張疊上去更會直接蓋掉另一台的名稱。
 * 放開滑鼠時，剛放下的節點若跟其他節點間距不足，就挪到「離放下位置最近、間距夠」的地方。
 * 只挪剛放下的那幾個，其他節點一律不動，不會牽一髮動全身。
 */

/** 節點之間至少要隔的距離：兩側徽章各伸出卡片約 8px，再留一點空隙 */
export const NODE_GAP = 24;

/* 量到實際尺寸前的備援（與 .vmNode 一致） */
const FALLBACK_SIZE = { w: 180, h: 68 };

function sizeOf(node) {
  return {
    w: node.measured?.width ?? node.width ?? node.style?.width ?? FALLBACK_SIZE.w,
    h: node.measured?.height ?? node.height ?? node.style?.height ?? FALLBACK_SIZE.h,
  };
}

/**
 * 在障礙之間找離 rect 目前位置最近、跟每個障礙都隔 gap 以上的位置。
 * 最近的空位不是原位，就一定貼在某個障礙往外推 gap 的邊上（或兩條邊的交角），
 * 所以候選座標只要取原位與每個障礙四邊外推後的位置，兩兩組合找最近的空位即可。
 *
 * @param {{ x: number, y: number, w: number, h: number }} rect
 * @param {{ x: number, y: number, w: number, h: number }[]} obstacles
 * @returns {{ x: number, y: number } | null} 原位就夠空回傳 null
 */
export function nearestFreeSpot(rect, obstacles, gap = NODE_GAP) {
  const blocked = (x, y) => obstacles.some((o) => (
    x < o.x + o.w + gap && o.x - gap < x + rect.w
    && y < o.y + o.h + gap && o.y - gap < y + rect.h
  ));
  if (!blocked(rect.x, rect.y)) return null;

  const xs = [rect.x, ...obstacles.flatMap((o) => [o.x - gap - rect.w, o.x + o.w + gap])];
  const ys = [rect.y, ...obstacles.flatMap((o) => [o.y - gap - rect.h, o.y + o.h + gap])];
  let best = null;
  for (const x of xs) {
    for (const y of ys) {
      const distance = Math.hypot(x - rect.x, y - rect.y);
      if (best && distance >= best.distance) continue;
      if (!blocked(x, y)) best = { x, y, distance };
    }
  }
  return best && { x: best.x, y: best.y };
}

/**
 * @param {Array} nodes 畫布上所有節點（ReactFlow 格式，剛放下的已在放下的位置）
 * @param {Iterable<string>} droppedIds 剛放下的節點 id
 * @param {{ gap?: number, movable?: (node) => boolean }} [options]
 *   movable：哪些放下的節點會被推開（預設全部）；不推的照放，但仍算別人的障礙
 * @returns {Map<string, { x: number, y: number }>} 要挪的節點 → 新位置（不用挪的不在裡面）
 */
export function settleDroppedNodes(nodes, droppedIds, { gap = NODE_GAP, movable = () => true } = {}) {
  const dropped = new Set(droppedIds);
  const visible = nodes.filter((node) => !node.hidden);
  /* 只跟同一層比：最上層（群組框、單機、網際網路）彼此比；
     群組框裡的機器座標相對於框，只跟同一個框裡的機器比（框會跟著機器長大，不必躲框外的東西） */
  const layerOf = (node) => node.parentId ?? "";
  const rectOf = (node) => ({ ...sizeOf(node), x: node.position.x, y: node.position.y });
  const placed = new Map(); // 層 → 已放好的範圍
  const place = (node, rect) => {
    const layer = layerOf(node);
    if (!placed.has(layer)) placed.set(layer, []);
    placed.get(layer).push(rect);
  };
  for (const node of visible) {
    if (!dropped.has(node.id)) place(node, rectOf(node));
  }

  const moves = new Map();
  /* 一次拖好幾台（框選後拖）：逐台安置，挪好的那台也算進後面的障礙 */
  for (const node of visible.filter((n) => dropped.has(n.id))) {
    const rect = rectOf(node);
    const spot = movable(node) ? nearestFreeSpot(rect, placed.get(layerOf(node)) ?? [], gap) : null;
    if (spot) moves.set(node.id, spot);
    place(node, spot ? { ...rect, ...spot } : rect);
  }
  return moves;
}

/**
 * 某些節點變大或換了位置（群組框跟著框內機器撐大）之後，把被它們蓋到的最上層節點挪開。
 * 被挪的節點若又壓到別的，接著挪那一個（連鎖），每個節點最多挪一次；固定的節點本身不動。
 *
 * @param {Array} nodes 畫布上所有節點（固定的節點已是新的位置與尺寸）
 * @param {Iterable<string>} fixedIds 不動、要讓位給它的節點
 * @param {{ gap?: number }} [options]
 * @returns {Map<string, { x: number, y: number }>} 要挪的節點 → 新位置
 */
export function makeRoomFor(nodes, fixedIds, { gap = NODE_GAP } = {}) {
  const topLevel = nodes.filter((node) => !node.parentId && !node.hidden);
  const rects = new Map(topLevel.map((node) => [node.id, { ...sizeOf(node), x: node.position.x, y: node.position.y }]));
  const settled = new Set([...fixedIds].filter((id) => rects.has(id)));
  const queue = [...settled];
  const moves = new Map();
  const tooClose = (a, b) => (
    a.x < b.x + b.w + gap && b.x - gap < a.x + a.w
    && a.y < b.y + b.h + gap && b.y - gap < a.y + a.h
  );
  while (queue.length) {
    const pusher = rects.get(queue.shift());
    for (const node of topLevel) {
      if (settled.has(node.id)) continue;
      const rect = rects.get(node.id);
      if (!tooClose(pusher, rect)) continue;
      const spot = nearestFreeSpot(rect, [...settled].map((id) => rects.get(id)), gap);
      if (!spot) continue;
      rects.set(node.id, { ...rect, ...spot });
      moves.set(node.id, spot);
      settled.add(node.id);
      queue.push(node.id);
    }
  }
  return moves;
}

/**
 * 給 onNodeDragStop 用：畫布上的節點以拖曳結束時的最終位置為準（store 可能還慢一拍），算出要挪的。
 * @param {Array} canvasNodes 畫布上所有節點（rfInstance.getNodes() 或頁面的 nodes state）
 * @param {Array} draggedNodes onNodeDragStop 給的拖曳節點
 * @returns {{ moves: Map<string, {x: number, y: number}>, dragged: Array }}
 *   moves 給 applyMoves 套到畫布；dragged 是挪好位置的拖曳節點（存佈局用）
 */
export function settleDraggedNodes(canvasNodes, draggedNodes, options) {
  const finalById = new Map((draggedNodes ?? []).map((node) => [node.id, node]));
  const current = canvasNodes.map((node) => (
    finalById.has(node.id) ? { ...node, position: finalById.get(node.id).position } : node
  ));
  const moves = settleDroppedNodes(current, finalById.keys(), options);
  return { moves, dragged: applyMoves([...finalById.values()], moves) };
}

/** 把挪動套到節點陣列上；沒有要挪的就原陣列照回，不觸發重繪 */
export function applyMoves(nodes, moves) {
  if (!moves.size) return nodes;
  return nodes.map((node) => (moves.has(node.id) ? { ...node, position: moves.get(node.id) } : node));
}
