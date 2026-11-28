/**
 * 像素圖的資料與產生器：用字元格描述一張圖（每個字元一格，"." 是空白），
 * 畫的時候把同一列、同一色的連續格併成一段 path，SVG 節點數才不會爆。
 *
 * 純函式、不碰 DOM／React：登入頁（frontend）與官網（site）共用同一份。
 * 顏色不寫在這裡，由使用端用 palette 把字元對應到 CSS 變數，深色模式才換得了色。
 */

/** 字元格 → { 字元: SVG path d }；寬高取最長的一列與列數 */
export function rowsToPaths(rows) {
  const paths = {};
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x];
      if (ch === "." || ch === " ") {
        x += 1;
        continue;
      }
      let end = x + 1;
      while (end < row.length && row[end] === ch) end += 1;
      paths[ch] = `${paths[ch] ?? ""}M${x} ${y}h${end - x}v1h${x - end}z`;
      x = end;
    }
  });
  return paths;
}

export function gridSize(rows) {
  return { w: rows.reduce((max, row) => Math.max(max, row.length), 0), h: rows.length };
}

/**
 * 像素雲：幾顆圓疊起來量化成格子，底部切平。
 * 字元：o 外框（outline 時才有）、f 雲身、h 左上受光、s 底部陰影。
 * @param {Array<[number, number, number]>} blobs 圓心 x、圓心 y、半徑（單位是格）
 */
export function cloudRows(w, h, blobs, { outline = false, shade = 2, highlight = true } = {}) {
  const inside = (x, y) =>
    x >= 0 && y >= 0 && x < w && y < h &&
    blobs.some(([cx, cy, r]) => (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r);
  const edge = (x, y) =>
    !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1) || !inside(x, y + 1);
  const body = (x, y) => inside(x, y) && !(outline && edge(x, y));

  const rows = [];
  for (let y = 0; y < h; y += 1) {
    let row = "";
    for (let x = 0; x < w; x += 1) {
      if (!inside(x, y)) row += ".";
      else if (outline && edge(x, y)) row += "o";
      else if (y >= h - shade - (outline ? 1 : 0)) row += "s";
      else if (highlight && y < h * 0.55 && (!body(x, y - 1) || (!body(x - 1, y) && y < h * 0.4))) row += "h";
      else row += "f";
    }
    rows.push(row);
  }
  return rows;
}

/* 打開的書（章魚學士坐在上面）：g 深藍外框、a 淡藍內框、c 書頁、b 書頁陰影、d 金色封面、j 封面暗面 */
function bookPageRow(inset, fill = "c") {
  const n = 14 - inset;
  return `${".".repeat(inset)}ga${fill.repeat(n)}bggb${fill.repeat(n)}ag${".".repeat(inset)}`;
}
export const BOOK = [
  bookPageRow(2),
  bookPageRow(2),
  bookPageRow(1),
  bookPageRow(1),
  bookPageRow(0),
  `ga${"b".repeat(14)}bggb${"b".repeat(14)}ag`,
  `g${"d".repeat(11)}${"b".repeat(12)}${"d".repeat(11)}g`,
  `${"g".repeat(12)}${"d".repeat(5)}jj${"d".repeat(5)}${"g".repeat(12)}`,
  `${".".repeat(12)}${"g".repeat(12)}${".".repeat(12)}`,
];

/* 十字星與星芒（海報風的金色點綴）、2×2 點點方陣 */
export const PLUS = [".x.", "xxx", ".x."];
export const SPARKLE = ["..x..", "..x..", "xxXxx", "..x..", "..x.."];
export const DOTS = ["x.x.x", ".....", "x.x.x", ".....", "x.x.x"];

/* SkyLab 字標：品牌標誌的 5×7 模組方塊字（35×7 模組），上 4 列 t、下 3 列 b 兩種色 */
export const WORDMARK = [
  ".tttt.tt..........tt..........tt...",
  "tt....tt....tt.tt.tt..........tt...",
  "tt....tt.tt.tt.tt.tt....tttt..tttt.",
  ".ttt..tttt...tttt.tt.......tt.tt.tt",
  "...bb.bbbb.....bb.bb.....bbbb.bb.bb",
  "...bb.bb.bb.bb.bb.bb....bb.bb.bb.bb",
  "bbbb..bb.bb..bbb..bbbbb..bbbb.bbbb.",
];
