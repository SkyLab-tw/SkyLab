import { cloudRows } from "./pixelArt";

/* 像素登入頁與官網像素版用到的圖：章魚背後的大雲（有外框，同品牌標誌）、背景的柔和雲、底部雲海。
   形狀在模組載入時算一次 */

export const HERO_CLOUD = cloudRows(
  58,
  24,
  [
    [10, 19, 7],
    [19, 17, 8],
    [39, 17, 8],
    [48, 19, 7],
    [26, 11, 10.5],
    [38, 12, 7.5],
    [14, 15, 6],
  ],
  { outline: true, shade: 2 },
);

/* 海報風的柔和雲：無外框，雲身＋底部一條陰影 */
const soft = (w, h, blobs) => cloudRows(w, h, blobs, { shade: 2, highlight: false });

export const SKY_CLOUDS = {
  a: soft(34, 11, [[9, 8, 5], [17, 6, 6.5], [26, 8, 5]]),
  b: soft(24, 8, [[7, 6, 4], [13, 4.5, 4.5], [19, 6, 3.6]]),
  c: soft(44, 13, [[10, 10, 6], [21, 7, 8], [33, 9, 6.5], [40, 11, 4]]),
  d: soft(18, 6, [[5, 5, 3], [10, 3.6, 3.6], [14, 5, 3]]),
};

/* 底部雲海：一長條起伏的雲，決定性的圓（不用亂數，每次畫都一樣） */
function seaRows(w, h, seed) {
  const blobs = [];
  for (let x = -4, i = 0; x < w + 8; i += 1) {
    const r = 5 + ((i * 7 + seed) % 5);
    // 圓心壓在底線附近、彼此重疊：大圓冒得高、小圓只露一點，雲頂起伏但不會斷開
    blobs.push([x, h + 1 - r * 0.55, r]);
    x += r * 1.05 + ((i * 5 + seed) % 3);
  }
  // 底下幾列補滿，雲與雲之間才不會露出縫
  return cloudRows(w, h, blobs, { shade: 0, highlight: false }).map((row, y) =>
    y >= h - 4 ? "f".repeat(w) : row,
  );
}
export const CLOUD_SEA_BACK = seaRows(260, 16, 2);
export const CLOUD_SEA_FRONT = seaRows(260, 11, 5);
