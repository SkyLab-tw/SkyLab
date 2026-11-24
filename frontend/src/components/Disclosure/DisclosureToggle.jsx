import MIcon from "../MIcon";
import styles from "./Disclosure.module.scss";

/**
 * 行內收合（Disclosure variant="inline"）的按鈕版：展開的內容不接在收合列下面時用，
 * 例如「顯示已失效的金鑰」把列併進上方表格，沒辦法包在 <details> 裡。
 * 樣子跟行內收合一樣：只有「文字＋向下箭頭」、沒有底色，平常淡色、滑過或展開變主色，展開時箭頭轉半圈。
 * 字級跟著外框（頁面用 className 設）。
 *
 * @param {boolean}   open      目前是否展開（同步到 aria-expanded）
 * @param {Function}  onToggle  點了切換
 * @param {ReactNode} children  按鈕文字（展開與收合可以給不同說法）
 * @param {string}    className 排版、字級
 * 其餘屬性（例如 aria-controls、data-guide）掛在 <button> 上
 */
export default function DisclosureToggle({ open, onToggle, children, className, ...rest }) {
  return (
    <button
      type="button"
      {...rest}
      className={[styles.toggle, className].filter(Boolean).join(" ")}
      aria-expanded={Boolean(open)}
      onClick={onToggle}
    >
      <span className={styles.label}>{children}</span>
      <MIcon name="expand_more" size={16} className={styles.chevron} />
    </button>
  );
}
