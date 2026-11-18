import { useId, useState } from "react";
import MIcon from "../MIcon";
import Collapse from "../Collapse/Collapse";
import styles from "./Disclosure.module.scss";

/**
 * 全站共用的收合：收合列是按鈕（aria-expanded／aria-controls），內容包在共用 Collapse 裡，
 * 展開收合時高度平滑過渡、內容淡入淡出（原本用原生 <details>，內容會直接出現／消失）。
 * 不用瀏覽器原生的 ▶ 三角形，一律是向下箭頭、展開時轉半圈。兩種樣子：
 *
 * - variant="boxed"（預設）：表單底部的「進階設定」這類。整行可點的白底細框列，14px／500，
 *   左邊選填圖示（主色）＋標題，右邊選填的淡色說明（如「選填」）＋箭頭；內容接在列下方 16px、
 *   跟上方欄位對齊（不包進框裡）。
 * - variant="inline"：補充資訊的行內收合（執行證據、錯誤詳情、工具紀錄）。只有「文字＋箭頭」、沒有框，
 *   字級跟著所在位置（在外框用 className 設），粗細 500；平常淡色，滑過或展開變主色。
 *   內容緊接在收合列下面，間距由內容自己決定。
 *
 * 收起時內容仍掛著（動畫要用），但 inert：點不到、Tab 不進去、讀屏略過。
 *
 * @param {ReactNode} label         收合列標題
 * @param {"boxed"|"inline"} variant 樣子
 * @param {string}    icon          標題前的 MIcon 名稱（boxed，主色，選填）
 * @param {ReactNode} meta          標題右側的淡色說明（boxed，例如「選填」，選填）
 * @param {boolean}   defaultOpen   一開始就展開
 * @param {string}    className     外框額外樣式（排版、字級、上方分隔線之類）
 * @param {string}    bodyClassName 內容區額外樣式（例如欄位的 grid）
 * 其餘屬性（例如導覽用的 data-guide）掛在外框上
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
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const classes = [styles.disclosure, inline && styles.inline, className].filter(Boolean).join(" ");
  return (
    <div {...rest} className={classes}>
      <button
        type="button"
        className={styles.summary}
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
      >
        {icon ? <MIcon name={icon} size={18} className={styles.icon} /> : null}
        <span className={styles.label}>{label}</span>
        {meta ? <span className={styles.meta}>{meta}</span> : null}
        <MIcon name="expand_more" size={inline ? 16 : 20} className={styles.chevron} />
      </button>
      <Collapse id={bodyId} open={open}>
        {/* boxed 內容接在列下方 16px；inline 緊接在下面，間距由內容自己決定 */}
        <div className={[inline ? null : styles.body, bodyClassName].filter(Boolean).join(" ") || undefined}>{children}</div>
      </Collapse>
    </div>
  );
}
