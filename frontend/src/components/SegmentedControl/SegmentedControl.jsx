import MIcon from "../MIcon";
import styles from "./SegmentedControl.module.scss";

/**
 * 全站共用的分段切換器（segmented control）。
 * 用於互斥選項的即時切換，分兩種份量：
 * - 預設（實心）：清單篩選（狀態＋數量）與表單選值（申請模式、題型…），選中段主色填滿，是畫面上的主要操作。
 * - quiet（輕量）：檢視選項——資料不變、只換呈現（時間區間、圖表指標、程式語言），沒有軌道與陰影、選中段不填色，
 *   只用主色細框＋深色字標示，放在頁面分頁旁或圖表標頭不會搶過分頁與內容。
 * 超過 4 個選項時，請在 className 加上 max-width:100% + overflow-x:auto 讓窄螢幕可橫向捲動。
 *
 * @param {Array}    options   [{ value, label, icon?, badge?, buttonProps? }]，icon 為可選的 MIcon 名稱，
 *                             badge 為可選的數量徽章，buttonProps 為附加到該段按鈕的原生屬性（如導覽用 data-*）
 * @param {string}   value     目前選中的 value
 * @param {Function} onChange  (value) => void
 * @param {string}   ariaLabel 群組的無障礙名稱
 * @param {string}   className 額外樣式
 * @param {boolean}  compact   各段內距縮成 0 8px：給 240px 以下的窄容器（側邊欄分頁），英日文才放得下
 * @param {boolean}  fullWidth 撐滿容器寬度、各段平分：不要在頁面 SCSS 覆寫元件內部的按鈕
 * @param {boolean}  quiet     輕量版：給檢視選項（見上）；切換「看哪一台／哪一份」這類主要操作仍用實心
 */
export default function SegmentedControl({
  options,
  value,
  onChange,
  ariaLabel,
  className,
  compact = false,
  fullWidth = false,
  quiet = false,
}) {
  const classes = [
    styles.segment,
    compact && styles.segmentCompact,
    fullWidth && styles.segmentFullWidth,
    quiet && styles.segmentQuiet,
    className,
  ].filter(Boolean).join(" ");
  return (
    <div
      className={classes}
      role="group"
      aria-label={ariaLabel}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          {...option.buttonProps}
          className={`${styles.segmentBtn} ${value === option.value ? styles.segmentActive : ""}`}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
        >
          {option.icon ? <MIcon name={option.icon} size={14} /> : null}
          {option.label}
          {option.badge != null ? <span className={styles.segmentBadge}>{option.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}
