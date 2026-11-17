import { useRef } from "react";
import MIcon from "../MIcon";
import styles from "./Tabs.module.scss";

/**
 * 全站共用的分頁（tabs）：切換「整塊內容」用。分兩種：
 * - 區塊分頁（預設）：卡片、區塊、側欄裡的分頁，選中的分頁字下一條 2px 主色短指示條，刻意低調。
 * - 頁面分頁（page）：標題下方、切換整頁主要內容的分頁，圖示放進圓角方塊，選中的方塊換主色實心，
 *   字 16px、列高 44px，份量比區塊分頁重一階，也壓得過旁邊的篩選。
 * 跟 SegmentedControl 分工——分頁用 Tabs；篩選同一份清單（狀態、類型）與選項（時間區間、圖表指標、表單模式）
 * 用 SegmentedControl，兩者並排時一眼分得出來。
 *
 * 無障礙：role="tablist"／"tab"＋aria-selected；只有選中的分頁在 Tab 鍵順序裡，
 * 左右鍵（頭尾相接）、Home／End 移動並直接切換。分頁放不下時自己橫向捲動。
 *
 * @param {Array}    options   [{ value, label, icon?, badge?, buttonProps? }]：icon 為 MIcon 名稱，
 *                             badge 為數量徽章（null／undefined 不顯示），buttonProps 掛在該分頁按鈕上（如導覽用 data-*）
 * @param {string}   value     目前選中的 value
 * @param {Function} onChange  (value) => void
 * @param {string}   ariaLabel 分頁列的無障礙名稱
 * @param {string}   className 額外樣式（排版用，例如 align-self；不要覆寫元件內部）
 * @param {boolean}  compact   各分頁左右內距縮成 8px：給 240px 以下的窄容器（側邊欄）
 * @param {boolean}  fullWidth 撐滿容器寬度、各分頁平分
 * @param {boolean}  page      頁面分頁：每個分頁都要給 icon（放進圓角方塊），整列往左拉一個內距，
 *                             第一個方塊對齊頁面標題左緣。分頁列到下方內容的間距由頁面用 @include page-tabs-row 收成 12px
 */
export default function Tabs({
  options,
  value,
  onChange,
  ariaLabel,
  className,
  compact = false,
  fullWidth = false,
  page = false,
}) {
  const listRef = useRef(null);
  const classes = [
    styles.tabs,
    compact && styles.tabsCompact,
    fullWidth && styles.tabsFullWidth,
    page && styles.tabsPage,
    className,
  ].filter(Boolean).join(" ");

  /* 沒有任何分頁選中時（value 對不到），讓第一個分頁留在 Tab 鍵順序裡，鍵盤才進得來 */
  const selectedIndex = options.findIndex((option) => option.value === value);
  const focusableIndex = selectedIndex >= 0 ? selectedIndex : 0;

  const moveTo = (index) => {
    const next = (index + options.length) % options.length;
    const option = options[next];
    if (!option) return;
    onChange(option.value);
    listRef.current?.children[next]?.focus();
  };

  const onKeyDown = (event) => {
    const current = focusableIndex;
    if (event.key === "ArrowRight") moveTo(current + 1);
    else if (event.key === "ArrowLeft") moveTo(current - 1);
    else if (event.key === "Home") moveTo(0);
    else if (event.key === "End") moveTo(options.length - 1);
    else return;
    event.preventDefault();
  };

  return (
    <div ref={listRef} className={classes} role="tablist" aria-label={ariaLabel} onKeyDown={onKeyDown}>
      {options.map((option, index) => {
        const selected = index === selectedIndex;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            {...option.buttonProps}
            aria-selected={selected}
            tabIndex={index === focusableIndex ? 0 : -1}
            className={`${styles.tab}${selected ? ` ${styles.tabActive}` : ""}`}
            onClick={() => onChange(option.value)}
          >
            {option.icon ? (
              page
                ? <span className={styles.iconBox}><MIcon name={option.icon} size={18} /></span>
                : <MIcon name={option.icon} size={16} />
            ) : null}
            {/* data-label 給 CSS 用選中字重預留寬度（見 .label::after），切換分頁時後面的分頁才不會左右跳 */}
            <span className={styles.label} data-label={typeof option.label === "string" ? option.label : undefined}>
              <span className={styles.labelText}>{option.label}</span>
            </span>
            {option.badge != null ? <span className={styles.badge}>{option.badge}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
