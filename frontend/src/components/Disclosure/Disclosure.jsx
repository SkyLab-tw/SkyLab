import MIcon from "../MIcon";
import styles from "./Disclosure.module.scss";

/**
 * 全站共用的收合，用原生 <details>／<summary>（鍵盤 Enter／Space 與螢幕閱讀器的展開狀態都是內建的），
 * 不用瀏覽器原生的 ▶ 三角形，一律是向下箭頭、展開時轉半圈。兩種樣子：
 *
 * - variant="boxed"（預設）：表單底部的「進階設定」這類。整行可點的白底細框列，14px／500，
 *   左邊選填圖示（主色）＋標題，右邊選填的淡色說明（如「選填」）＋箭頭；內容接在列下方 16px、
 *   跟上方欄位對齊（不包進框裡）。
 * - variant="inline"：補充資訊的行內收合（執行證據、錯誤詳情、工具紀錄）。只有「文字＋箭頭」、沒有框，
 *   字級跟著所在位置（在外框用 className 設），粗細 500；平常淡色，滑過或展開變主色。
 *   內容緊接在收合列下面，間距由內容自己決定。
 *
 * @param {ReactNode} label         收合列標題
 * @param {"boxed"|"inline"} variant 樣子
 * @param {string}    icon          標題前的 MIcon 名稱（boxed，主色，選填）
 * @param {ReactNode} meta          標題右側的淡色說明（boxed，例如「選填」，選填）
 * @param {boolean}   defaultOpen   一開始就展開
 * @param {string}    className     外框額外樣式（排版、字級、上方分隔線之類）
 * @param {string}    bodyClassName 內容區額外樣式（例如欄位的 grid）
 * 其餘屬性（例如導覽用的 data-guide）掛在 <details> 上
 */
export default function Disclosure({
  label,
  variant = "boxed",
  icon,
  meta,
  defaultOpen = false,
  className,
  bodyClassName,
  children,
  ...rest
}) {
  const inline = variant === "inline";
  const classes = [styles.disclosure, inline && styles.inline, className].filter(Boolean).join(" ");
  return (
    <details {...rest} className={classes} open={defaultOpen || undefined}>
      <summary className={styles.summary}>
        {icon ? <MIcon name={icon} size={18} className={styles.icon} /> : null}
        <span className={styles.label}>{label}</span>
        {meta ? <span className={styles.meta}>{meta}</span> : null}
        <MIcon name="expand_more" size={inline ? 16 : 20} className={styles.chevron} />
      </summary>
      <div className={`${styles.body}${bodyClassName ? ` ${bodyClassName}` : ""}`}>{children}</div>
    </details>
  );
}
