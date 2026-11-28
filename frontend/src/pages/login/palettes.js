/* 登入頁像素圖的配色：字元 → CSS 變數（變數定義在 PageShell.module.scss 的 .page，深色模式在那裡換） */

export const CLOUD_PALETTE = {
  o: "var(--px-cloud-line)",
  f: "var(--px-cloud-fill)",
  h: "var(--px-cloud-hi)",
  s: "var(--px-cloud-shade)",
};
export const BOOK_PALETTE = {
  g: "var(--px-book-line)",
  a: "var(--px-cloud-line)",
  c: "var(--px-book-page)",
  b: "var(--px-book-shade)",
  d: "var(--px-gold)",
  j: "var(--px-gold-dark)",
};
export const WORDMARK_PALETTE = { t: "var(--px-word-top)", b: "var(--px-word-bottom)" };

export const GOLD_PALETTE = { x: "var(--px-gold)", X: "var(--px-gold-hi)" };
export const BLUE_PALETTE = { x: "var(--px-star-blue)", X: "var(--px-star-blue)" };
export const DOT_PALETTE = { x: "var(--px-dots)" };

export const SKY_CLOUD_PALETTE = { f: "var(--px-sky-cloud)", s: "var(--px-sky-cloud-shade)" };
export const SEA_BACK_PALETTE = { f: "var(--px-sea-back)" };
export const SEA_FRONT_PALETTE = { f: "var(--px-sea-front)" };
