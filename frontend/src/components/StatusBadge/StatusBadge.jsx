/**
 * StatusBadge
 * 狀態徽章：狀態色 12% 淡底膠囊＋狀態色文字，不加外框（規格見 style guide「狀態 Badge」）。
 * 同一個狀態在不同頁面要長得一樣（例如 AI 導師檢查的老師端與學生端），就都用這個元件，
 * 不要再各頁手抄 .badge_success 這類色調類別。
 *
 * props
 * - tone       success／danger／info／pending／muted；primary 給「老師有回覆」這類非狀態的主色標記
 * - icon       選填，Material Icons 名稱，放在文字前面。旁邊已經有同義圖示（例如列首的狀態圖示）就不要再放
 * - className  只拿來放位置（grid 欄位、對齊），不要覆寫顏色
 * - 其餘屬性（title、aria-*、data-*）原樣傳到外層 span
 */

import MIcon from "../MIcon";
import styles from "./StatusBadge.module.scss";

const TONES = new Set(["success", "danger", "info", "pending", "muted", "primary"]);

export default function StatusBadge({ tone = "muted", icon = null, className = "", children, ...rest }) {
  const classes = [styles.badge, styles[TONES.has(tone) ? tone : "muted"], className].filter(Boolean).join(" ");
  return (
    <span className={classes} {...rest}>
      {icon && <MIcon name={icon} size={14} />}
      {children}
    </span>
  );
}
