/**
 * 連線標籤該放在哪裡（純函式，不碰 React）。
 *
 * 標籤預設貼在「這條規則的主體」那台機器旁 LABEL_GAP 處：多條線匯聚到同一台時，
 * 放中點會擠成一排、看不出哪個標籤屬於哪條線，中段也常被沿途的節點蓋住。
 *
 * 但機器可以自由拖，兩台一靠近、或第三台剛好擋在線上，固定位置的標籤就會被節點蓋掉。
 * 所以依序找一個不壓到任何節點的位置：
 * 1. 預設點
 * 2. 沿同一條線往前後滑：標籤仍貼在自己的線上，一看就知道是哪條
 * 3. 線整段都被擋住（兩台緊貼、線短到放不下標籤）：從預設點往下／上／右／左移到空處，
 *    回傳一條引線指回線上，才看得出標籤屬於哪條線
 * 都找不到就留在預設點（畫面把標籤疊在節點上層，至少不會整個被蓋掉）。
 * 已經放好的其他標籤也當障礙，標籤之間才不會疊在一起。
 */

/** 標籤與所屬節點的距離。固定距離而非固定比例：長線的標籤才不會飄到沿途的節點上，短線的也不會貼在節點身上 */
export const LABEL_GAP = 52;
/** 節點往外留的安全距離：來源徽章、對外開放數都伸出卡片外約 8–10px，標籤不該壓到 */
export const NODE_CLEARANCE = 10;
/** 標籤彼此之間留的空隙 */
export const LABEL_SPACING = 4;

/* 沿線滑動的步距 */
const SLIDE_STEP = 12;
/* 移出線外時每次多移的距離與上限：再遠就跟線脫節，不如留在原處 */
const NUDGE_STEP = 8;
const NUDGE_MAX = 160;
/* 弧長取樣數：貝茲的 t 與弧長不成正比，垂直連線尤其明顯，直接用 t 估距離會讓標籤飄進節點 */
const SAMPLES = 48;

/* 移出線外的方向：先往下（多數連線是左右走向，標籤落在兩台下方最好讀），
   標籤一律往遠離線的那側展開 */
const NUDGES = [
  { dx: 0, dy: 1, align: { ax: -0.5, ay: 0 } },
  { dx: 0, dy: -1, align: { ax: -0.5, ay: -1 } },
  { dx: 1, dy: 0, align: { ax: 0, ay: -0.5 } },
  { dx: -1, dy: 0, align: { ax: -1, ay: -0.5 } },
];

/** 解析 getBezierPath 產生的 "M sx,sy C c1x,c1y c2x,c2y tx,ty" */
export function parsePath(d) {
  const nums = typeof d === "string" ? d.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/gi) : null;
  return nums && nums.length >= 8 ? nums.slice(0, 8).map(Number) : null;
}

function bezierAt([x0, y0, x1, y1, x2, y2, x3, y3], t) {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const e = t * t * t;
  return {
    x: a * x0 + b * x1 + c * x2 + e * x3,
    y: a * y0 + b * y1 + c * y2 + e * y3,
  };
}

/** 從錨點那端沿路徑取樣，每點記下累積弧長 s */
function sampleFromAnchor(curve, fromEnd) {
  const points = [];
  let travelled = 0;
  let prev = null;
  for (let i = 0; i <= SAMPLES; i++) {
    const ratio = i / SAMPLES;
    const point = bezierAt(curve, fromEnd ? 1 - ratio : ratio);
    if (prev) travelled += Math.hypot(point.x - prev.x, point.y - prev.y);
    points.push({ ...point, s: travelled });
    prev = point;
  }
  return points;
}

function pointAtLength(samples, s) {
  for (let i = 1; i < samples.length; i++) {
    if (samples[i].s >= s) {
      const a = samples[i - 1];
      const b = samples[i];
      const k = (s - a.s) / ((b.s - a.s) || 1);
      return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k };
    }
  }
  const last = samples[samples.length - 1];
  return { x: last.x, y: last.y };
}

/** 標籤往遠離自己節點的方向展開，否則長標籤會往回蓋住節點 */
function alignAway(point, anchor) {
  const awayX = point.x - anchor.x;
  const awayY = point.y - anchor.y;
  return Math.abs(awayX) > Math.abs(awayY)
    ? { ax: awayX >= 0 ? 0 : -1, ay: -0.5 }
    : { ax: -0.5, ay: awayY >= 0 ? 0 : -1 };
}

function labelRect(point, align, size) {
  return {
    x: point.x + align.ax * size.w,
    y: point.y + align.ay * size.h,
    w: size.w,
    h: size.h,
  };
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

/**
 * @param {string} d 連線的 SVG path（getBezierPath 的格式）
 * @param {object} options
 * @param {boolean} options.nearTarget 標籤貼目標端（入站的主體是目標機器）還是來源端
 * @param {{ w: number, h: number }} options.size 標籤尺寸
 * @param {{ x: number, y: number, w: number, h: number }[]} [options.obstacles] 畫布上的節點範圍（不含安全距離）
 * @param {{ x: number, y: number, w: number, h: number }[]} [options.labels] 已經放好的其他標籤範圍
 * @param {{ x: number, y: number }} [options.shift] 同一對節點間多條線時，標籤額外錯開的量
 * @returns {{ x: number, y: number, ax: number, ay: number, clear: boolean,
 *   rect: { x: number, y: number, w: number, h: number },
 *   leader: { x1: number, y1: number, x2: number, y2: number } | null } | null}
 *   x／y 是對齊點，ax／ay 是標籤相對對齊點的平移比例（-0.5＝置中、-1＝整個往左／上）；
 *   rect＝標籤實際佔的範圍；clear＝沒壓到任何節點或標籤；leader＝標籤離開線時指回線上的引線。
 *   路徑解析不了回傳 null
 */
export function placeEdgeLabel(d, { nearTarget, size, obstacles = [], labels = [], shift = { x: 0, y: 0 } }) {
  const curve = parsePath(d);
  if (!curve) return null;

  const samples = sampleFromAnchor(curve, nearTarget);
  const total = samples[samples.length - 1].s;
  const anchor = samples[0];
  /* 整條線比一個間距還短：放中點 */
  const preferredS = total >= LABEL_GAP ? LABEL_GAP : total / 2;

  const margin = NODE_CLEARANCE;
  const reach = NUDGE_MAX + Math.max(size.w, size.h) + margin;
  const xs = samples.map((p) => p.x);
  const ys = samples.map((p) => p.y);
  const area = {
    x: Math.min(...xs) - reach,
    y: Math.min(...ys) - reach,
    w: Math.max(...xs) - Math.min(...xs) + reach * 2,
    h: Math.max(...ys) - Math.min(...ys) + reach * 2,
  };
  const grow = (r, by) => ({ x: r.x - by, y: r.y - by, w: r.w + by * 2, h: r.h + by * 2 });
  /* 只留這條線附近的節點與標籤，機器多時不必每個候選點都跟整張圖比 */
  const blockers = [
    ...obstacles.map((r) => grow(r, margin)),
    ...labels.map((r) => grow(r, LABEL_SPACING)),
  ].filter((r) => overlaps(r, area));
  const isFree = (rect) => !blockers.some((b) => overlaps(rect, b));

  const onPath = (s) => {
    const raw = pointAtLength(samples, s);
    const point = { x: raw.x + shift.x, y: raw.y + shift.y };
    const align = alignAway(raw, anchor);
    return { point, align, rect: labelRect(point, align, size) };
  };
  const onPathResult = ({ point, align, rect }, clear) => ({ ...point, ...align, rect, clear, leader: null });

  const preferred = onPath(preferredS);
  if (isFree(preferred.rect)) return onPathResult(preferred, true);

  /* 沿線前後滑，先往遠離自己節點的方向 */
  for (let k = 1; preferredS + k * SLIDE_STEP <= total || preferredS - k * SLIDE_STEP >= 0; k++) {
    for (const s of [preferredS + k * SLIDE_STEP, preferredS - k * SLIDE_STEP]) {
      if (s < 0 || s > total) continue;
      const candidate = onPath(s);
      if (isFree(candidate.rect)) return onPathResult(candidate, true);
    }
  }

  /* 線上沒有空位：移出線外，拉引線指回預設點 */
  const base = preferred.point;
  for (let offset = NUDGE_STEP; offset <= NUDGE_MAX; offset += NUDGE_STEP) {
    for (const { dx, dy, align } of NUDGES) {
      const point = { x: base.x + dx * offset, y: base.y + dy * offset };
      const rect = labelRect(point, align, size);
      if (!isFree(rect)) continue;
      return {
        ...point,
        ...align,
        rect,
        clear: true,
        leader: {
          x1: base.x,
          y1: base.y,
          x2: clamp(base.x, rect.x, rect.x + rect.w),
          y2: clamp(base.y, rect.y, rect.y + rect.h),
        },
      };
    }
  }

  return onPathResult(preferred, false);
}
