/* 票券的條碼：total 個項目各佔一段（項目多時一段代表數個），完成的排在前面。
   班級票券用它畫進度；課程票券只拿它當票根的花紋（completed 一律 0）。
   條寬與間距由 id 決定，同一張票每次都畫出同一組條碼，不同的票一眼分得出來。 */

export const MAX_BARS = 40;

/* 項目少時（例如 3 個）一個一條只剩幾塊粗色塊、不像條碼：
   改成每個畫一小叢細條、叢與叢之間留較寬的空隙，整張條碼至少這麼多條，仍看得出分成幾段 */
export const MIN_BARS = 24;

const WIDTHS = [1, 1, 2, 3];
const GROUP_GAP = 4;

/* FNV-1a 雜湊當種子，xorshift32 產生 0–1 的序列 */
function seeded(text) {
  let hash = 2166136261;
  for (const char of text) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return () => {
    hash ^= hash << 13;
    hash ^= hash >>> 17;
    hash ^= hash << 5;
    return (hash >>> 0) / 4294967296;
  };
}

/**
 * @returns {{ width: number, gap: number, done: boolean }[]} 相對寬度（flex-grow）與是否已完成；total 為 0 時回空陣列
 */
export function ticketBarcode(id, total, completed) {
  const items = Math.max(0, Math.floor(Number(total) || 0));
  const segments = Math.min(items, MAX_BARS);
  if (segments === 0) return [];

  const finished = Math.min(Math.max(0, Number(completed) || 0), items);
  let done = Math.round((finished / items) * segments);
  if (finished > 0) done = Math.max(1, done); // 完成一個就看得到
  if (finished < items) done = Math.min(segments - 1, done); // 沒做完就不會看起來全滿

  const perSegment = Math.ceil(MIN_BARS / segments);
  const random = seeded(String(id ?? ""));
  const bars = [];
  for (let segment = 0; segment < segments; segment += 1) {
    for (let index = 0; index < perSegment; index += 1) {
      const endOfSegment = index === perSegment - 1;
      const last = endOfSegment && segment === segments - 1;
      const width = WIDTHS[Math.floor(random() * WIDTHS.length)];
      let gap = 0;
      if (!last) gap = endOfSegment && perSegment > 1 ? GROUP_GAP + Math.floor(random() * 2) : 1 + Math.floor(random() * 2);
      bars.push({ width, gap, done: segment < done });
    }
  }
  return bars;
}
