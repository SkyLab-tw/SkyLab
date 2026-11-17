import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import MIcon from "../MIcon";
import ListboxPopover from "../ListboxPopover/ListboxPopover";
import useDialogPresence from "../../hooks/useDialogPresence";
import styles from "./SegmentedControl.module.scss";

/** 往上觀察幾層祖先的尺寸：收成下拉後自己變窄，要靠外層變寬才知道該試著展開回來 */
const OBSERVED_ANCESTORS = 8;

/**
 * 全站共用的分段切換器（segmented control）：互斥選項的即時切換——清單篩選（狀態＋數量徽章，可停用單段）、
 * 表單選值（申請模式、題型…）與檢視選項（時間區間、圖表指標、程式語言），一律同一種實心樣子：
 * 外框軌道、選中段主色填滿。窄容器（240px 以下的側欄）加 compact＋fullWidth。
 *
 * 放不下時自動收成下拉：整組換成一顆顯示目前選項的按鈕，點開是共用的 ListboxPopover，字不會被切掉；
 * 外層變寬、放得下時再自動展開回分段。做法是先照常排成分段量有沒有溢出（同一個 layout effect 內，
 * 畫面不會閃），收起後觀察自己與外層幾層祖先的尺寸，有變化就再試一次。頁面不用再加 overflow-x。
 * 收成下拉時 buttonProps（例如導覽用的 data-*）不在畫面上。
 *
 * @param {Array}    options   [{ value, label, icon?, badge?, buttonProps? }]，icon 為可選的 MIcon 名稱，
 *                             badge 為可選的數量徽章，buttonProps 為附加到該段按鈕的原生屬性（如導覽用 data-*、disabled）
 * @param {string}   value     目前選中的 value
 * @param {Function} onChange  (value) => void
 * @param {string}   ariaLabel 群組的無障礙名稱（收成下拉時也是清單的名稱）
 * @param {string}   className 額外樣式
 * @param {boolean}  compact   各段內距縮成 0 8px：給 240px 以下的窄容器（側邊欄分頁），英日文才放得下
 * @param {boolean}  fullWidth 撐滿容器寬度、各段平分：不要在頁面 SCSS 覆寫元件內部的按鈕
 */
export default function SegmentedControl({
  options,
  value,
  onChange,
  ariaLabel,
  className,
  compact = false,
  fullWidth = false,
}) {
  const groupRef = useRef(null);
  const triggerRef = useRef(null);
  const listId = useId();
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const collapsedRef = useRef(false);
  const menuOpenRef = useRef(false);
  collapsedRef.current = collapsed;
  menuOpenRef.current = menuOpen;
  const menu = useDialogPresence(menuOpen && collapsed, 130);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  // 每次以分段排出來之後量一次：放不下就收成下拉（在畫面更新前完成，不會先閃出被切掉的分段）
  useLayoutEffect(() => {
    const group = groupRef.current;
    if (!group || collapsed) return;
    if (group.scrollWidth > group.clientWidth + 1) setCollapsed(true);
    else if (menuOpenRef.current) setMenuOpen(false);
  });

  // 自己或外層「寬度」變了：分段狀態就直接量一次（變窄放不下就收）；下拉狀態就試著展開，
  // 展開後放不下，上面的 layout effect 會在畫面更新前收回去。
  // 只看寬度（清單下方的內容自動更新、高度變了不算），清單開著時也不動，免得選到一半被關掉
  useEffect(() => {
    const group = groupRef.current;
    if (!group || typeof ResizeObserver === "undefined") return undefined;
    const widths = new Map();
    const observer = new ResizeObserver((entries = []) => {
      let widthChanged = false;
      for (const entry of entries) {
        const width = Math.round(entry.contentRect.width);
        if (widths.get(entry.target) !== width) widthChanged = true;
        widths.set(entry.target, width);
      }
      if (!widthChanged || menuOpenRef.current) return;
      if (collapsedRef.current) setCollapsed(false);
      else if (group.scrollWidth > group.clientWidth + 1) setCollapsed(true);
    });
    let node = group;
    for (let depth = 0; node && node !== document.body && depth <= OBSERVED_ANCESTORS; depth += 1) {
      observer.observe(node);
      node = node.parentElement;
    }
    return () => observer.disconnect();
  }, []);

  // 字型（含圖示字型）載完再試著展開重量：載入前圖示會先顯示成整串英文字，量到的寬度偏大、可能被誤收成下拉
  useEffect(() => {
    const fonts = typeof document !== "undefined" ? document.fonts : null;
    if (!fonts?.addEventListener) return undefined;
    let alive = true;
    const remeasure = () => {
      const group = groupRef.current;
      if (!alive || !group || menuOpenRef.current) return;
      if (collapsedRef.current) setCollapsed(false);
      else if (group.scrollWidth > group.clientWidth + 1) setCollapsed(true);
    };
    fonts.ready?.then(remeasure);
    fonts.addEventListener("loadingdone", remeasure);
    return () => {
      alive = false;
      fonts.removeEventListener("loadingdone", remeasure);
    };
  }, []);

  const classes = [
    styles.segment,
    compact && styles.segmentCompact,
    fullWidth && styles.segmentFullWidth,
    collapsed && styles.segmentCollapsed,
    className,
  ].filter(Boolean).join(" ");

  const renderContent = (option) => (
    <>
      {option.icon ? <MIcon name={option.icon} size={14} /> : null}
      {option.label}
      {option.badge != null ? <span className={styles.segmentBadge}>{option.badge}</span> : null}
    </>
  );

  if (collapsed) {
    const selected = options.find((option) => option.value === value);
    return (
      <div ref={groupRef} className={classes} role="group" aria-label={ariaLabel}>
        <button
          ref={triggerRef}
          type="button"
          className={styles.collapsedTrigger}
          aria-haspopup="listbox"
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? listId : undefined}
          onClick={() => setMenuOpen((open) => !open)}
          onKeyDown={(event) => {
            // 跟原生下拉一樣：上下鍵直接展開
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
            event.preventDefault();
            setMenuOpen(true);
          }}
        >
          <span className={styles.collapsedLabel}>{selected ? renderContent(selected) : null}</span>
          <MIcon name="expand_more" size={18} className={styles.collapsedChevron} />
        </button>
        {menu.open && (
          <ListboxPopover
            id={listId}
            anchorRef={triggerRef}
            ariaLabel={ariaLabel}
            options={options.map((option) => ({
              value: option.value,
              label: <span className={styles.optionLabel}>{renderContent(option)}</span>,
              disabled: Boolean(option.buttonProps?.disabled),
            }))}
            value={value}
            onSelect={onChange}
            onClose={closeMenu}
            closing={menu.closing}
          />
        )}
      </div>
    );
  }

  return (
    <div ref={groupRef} className={classes} role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          {...option.buttonProps}
          className={`${styles.segmentBtn} ${value === option.value ? styles.segmentActive : ""}`}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
        >
          {renderContent(option)}
        </button>
      ))}
    </div>
  );
}
