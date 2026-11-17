import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import MIcon from "../MIcon";
import ListboxPopover from "../ListboxPopover/ListboxPopover";
import useDialogPresence from "../../hooks/useDialogPresence";
import styles from "./Tabs.module.scss";

/** 往上觀察幾層祖先的寬度：收起幾個分頁後自己變窄，要靠外層變寬才知道能不能多排幾個回來 */
const OBSERVED_ANCESTORS = 8;

/** 外層是不是放不下（量的是整組：分頁列＋「更多」） */
const overflows = (root) => root.scrollWidth > root.clientWidth + 1;

/**
 * 全站共用的分頁（tabs）：切換「整塊內容」用，只有一種樣子——圖示放進 28px 圓角方塊，選中的方塊換主色實心白圖示、
 * 字加粗；字 16px、列高 44px，份量壓得過旁邊的篩選。頁面標題下方、卡片裡（例如 AI 用量監控明細）都用這一種。
 * 跟 SegmentedControl 分工——分頁用 Tabs；篩選同一份清單（狀態、類型）與選項（時間區間、圖表指標、表單模式）
 * 用 SegmentedControl，兩者並排時一眼分得出來。240px 以下的窄側欄放不下分頁，改用 SegmentedControl 的 compact＋fullWidth。
 *
 * 無障礙：role="tablist"／"tab"＋aria-selected；只有選中的分頁在 Tab 鍵順序裡，
 * 左右鍵（頭尾相接）、Home／End 移動並直接切換。
 *
 * 放不下時（窄螢幕）：放得下的分頁照常排（一律帶字），其餘收進最右邊的「更多」，點開是共用的 ListboxPopover；
 * 選中的分頁一定排在外面（選到收起來的那個，它會換到外面最後一格）。外層變寬就一個個排回來，全部放得下「更多」就消失。
 * 做法是先全部排開量有沒有溢出（同一個 layout effect 內，畫面不會閃），溢出就依各分頁寬度算出排得下幾個；
 * 之後觀察自己與外層幾層祖先的寬度，變了就重算。收進「更多」的分頁不在畫面上，它的 buttonProps（導覽用 data-*）也一樣。
 *
 * @param {Array}    options   [{ value, label, icon, badge?, buttonProps? }]：icon 為 MIcon 名稱（每個分頁都要給），
 *                             badge 為數量徽章（null／undefined 不顯示），buttonProps 掛在該分頁按鈕上（如導覽用 data-*）
 * @param {string}   value     目前選中的 value
 * @param {Function} onChange  (value) => void
 * @param {string}   ariaLabel 分頁列的無障礙名稱
 * @param {string}   className 額外樣式（排版用，例如 align-self；不要覆寫元件內部）
 * 整列往左拉一個內距，第一個方塊對齊容器左緣（頁面標題、卡片內容）。放在頁面標題下方時，
 * 分頁列到下方內容的間距由頁面用 @include page-tabs-row 收成 12px
 */
export default function Tabs({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}) {
  const { t } = useTranslation("common");
  const rootRef = useRef(null);
  const listRef = useRef(null);
  const moreRef = useRef(null);
  const moreMeasureRef = useRef(null);
  const pendingFocusRef = useRef(null);
  const menuId = useId();
  /* 排在外面的分頁數；null＝全部排開（也是量寬度時的狀態） */
  const [visibleCount, setVisibleCount] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const visibleCountRef = useRef(null);
  const menuOpenRef = useRef(false);
  visibleCountRef.current = visibleCount;
  menuOpenRef.current = menuOpen;

  /* 沒有任何分頁選中時（value 對不到），讓第一個分頁留在 Tab 鍵順序裡，鍵盤才進得來 */
  const selectedIndex = options.findIndex((option) => option.value === value);
  const focusableIndex = selectedIndex >= 0 ? selectedIndex : 0;

  /* 排在外面的是前 count 個；選中的若排在後面，換到第 count 格（前 count−1 個＋選中的） */
  const visibleIndexes = (count) => {
    const all = options.map((_, index) => index);
    if (count == null || count >= options.length) return all;
    if (focusableIndex < count) return all.slice(0, count);
    return [...all.slice(0, Math.max(count - 1, 0)), focusableIndex];
  };

  /* 全部排開的狀態下量：沒溢出回 null；溢出就照各分頁寬度算排得下幾個（至少一個，再不夠就橫向捲動） */
  const measure = useCallback(() => {
    const root = rootRef.current;
    const list = listRef.current;
    if (!root || !list || !overflows(root)) return null;
    const gap = parseFloat(getComputedStyle(list).columnGap) || 0;
    const widths = [...list.children].map((tab) => tab.getBoundingClientRect().width);
    const moreWidth = moreMeasureRef.current?.getBoundingClientRect().width ?? 0;
    const available = root.clientWidth;
    const active = focusableIndex;
    for (let count = options.length - 1; count >= 1; count -= 1) {
      const indexes = active < count
        ? widths.map((_, index) => index).slice(0, count)
        : [...widths.map((_, index) => index).slice(0, count - 1), active];
      const used = indexes.reduce((sum, index) => sum + (widths[index] ?? 0), 0) + gap * indexes.length + moreWidth;
      if (used <= available) return count;
    }
    return 1;
  }, [focusableIndex, options.length]);

  // 換了選中的分頁、或分頁的字／徽章變了：全部排開重量一次。
  // 要排在下面那個量寬度的 effect 前面：同一次提交裡先清成 null、再由量寬度的設回去；
  // 順序反過來，掛載時會先設好又被清掉，React 看狀態沒變就不再重繪，永遠收不起來
  const optionsSignature = options.map((option) => `${option.value}|${String(option.label)}|${option.badge ?? ""}`).join("\n");
  useLayoutEffect(() => {
    setVisibleCount(null);
  }, [value, optionsSignature]);

  // 全部排開時量一次：放不下就收（在畫面更新前完成，不會先閃出被切掉的分頁）
  useLayoutEffect(() => {
    if (visibleCount !== null) return;
    const count = measure();
    if (count !== null) setVisibleCount(count);
  });

  // 自己或外層「寬度」變了就全部排開重量（只看寬度；清單開著時不動，免得選到一半被關掉）
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === "undefined") return undefined;
    const widths = new Map();
    const observer = new ResizeObserver((entries = []) => {
      let widthChanged = false;
      for (const entry of entries) {
        const width = Math.round(entry.contentRect.width);
        if (widths.get(entry.target) !== width) widthChanged = true;
        widths.set(entry.target, width);
      }
      if (!widthChanged || menuOpenRef.current) return;
      if (visibleCountRef.current !== null) setVisibleCount(null);
      else {
        const count = measure();
        if (count !== null) setVisibleCount(count);
      }
    });
    let node = root;
    for (let depth = 0; node && node !== document.body && depth <= OBSERVED_ANCESTORS; depth += 1) {
      observer.observe(node);
      node = node.parentElement;
    }
    return () => observer.disconnect();
  }, [measure]);

  // 字型（含圖示字型）載完再全部排開重量：載入前圖示會先顯示成整串英文字，量到的寬度偏大、收太多進「更多」，
  // 而分頁列本身寬度沒變，上面的尺寸觀察不會觸發
  useEffect(() => {
    const fonts = typeof document !== "undefined" ? document.fonts : null;
    if (!fonts?.addEventListener) return undefined;
    let alive = true;
    const remeasure = () => {
      if (!alive || menuOpenRef.current) return;
      if (visibleCountRef.current !== null) setVisibleCount(null);
      else {
        const count = measure();
        if (count !== null) setVisibleCount(count);
      }
    };
    fonts.ready?.then(remeasure);
    fonts.addEventListener("loadingdone", remeasure);
    return () => {
      alive = false;
      fonts.removeEventListener("loadingdone", remeasure);
    };
  }, [measure]);

  // 鍵盤換分頁後，焦點跟到新選中的分頁（它可能剛從「更多」換到外面來）
  useEffect(() => {
    const target = pendingFocusRef.current;
    if (target == null) return;
    const tab = [...(listRef.current?.children ?? [])].find((el) => el.dataset.tabsValue === String(target));
    if (tab) {
      tab.focus();
      pendingFocusRef.current = null;
    }
  });

  const shown = visibleIndexes(visibleCount);
  const hidden = options.filter((_, index) => !shown.includes(index));
  const menu = useDialogPresence(menuOpen && hidden.length > 0, 130);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const moveTo = (index) => {
    const next = (index + options.length) % options.length;
    const option = options[next];
    if (!option) return;
    pendingFocusRef.current = option.value;
    onChange(option.value);
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

  const renderIconBox = (option, small = false) => (option.icon
    ? <span className={small ? styles.iconBoxSmall : styles.iconBox}><MIcon name={option.icon} size={small ? 16 : 18} /></span>
    : null);

  const moreLabel = t("Tabs.more");

  return (
    <div ref={rootRef} className={[styles.tabs, className].filter(Boolean).join(" ")}>
      <div ref={listRef} className={styles.tabList} role="tablist" aria-label={ariaLabel} onKeyDown={onKeyDown}>
        {shown.map((index) => {
          const option = options[index];
          const selected = index === selectedIndex;
          return (
            <button
              key={option.value}
              type="button"
              role="tab"
              data-tabs-value={String(option.value)}
              {...option.buttonProps}
              aria-selected={selected}
              tabIndex={index === focusableIndex ? 0 : -1}
              className={`${styles.tab}${selected ? ` ${styles.tabActive}` : ""}`}
              onClick={() => onChange(option.value)}
            >
              {renderIconBox(option)}
              {/* data-label 給 CSS 用選中字重預留寬度（見 .label::after），切換分頁時後面的分頁才不會左右跳 */}
              <span className={styles.label} data-label={typeof option.label === "string" ? option.label : undefined}>
                <span className={styles.labelText}>{option.label}</span>
              </span>
              {option.badge != null ? <span className={styles.badge}>{option.badge}</span> : null}
            </button>
          );
        })}
      </div>

      {hidden.length > 0 ? (
        <button
          ref={moreRef}
          type="button"
          className={styles.moreBtn}
          aria-haspopup="listbox"
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? menuId : undefined}
          onClick={() => setMenuOpen((open) => !open)}
          onKeyDown={(event) => {
            // 跟原生下拉一樣：上下鍵直接展開
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
            event.preventDefault();
            setMenuOpen(true);
          }}
        >
          {moreLabel}
          <MIcon name="expand_more" size={18} />
        </button>
      ) : (
        /* 量寬度用：全部排開時不顯示，只用來知道「更多」要佔多寬 */
        <span ref={moreMeasureRef} className={`${styles.moreBtn} ${styles.moreMeasure}`} aria-hidden="true">
          {moreLabel}
          <MIcon name="expand_more" size={18} />
        </span>
      )}

      {menu.open && (
        <ListboxPopover
          id={menuId}
          anchorRef={moreRef}
          ariaLabel={ariaLabel}
          options={hidden.map((option) => ({
            value: option.value,
            label: (
              <span className={styles.menuOption}>
                {renderIconBox(option, true)}
                <span className={styles.menuOptionText}>{option.label}</span>
                {option.badge != null ? <span className={styles.badge}>{option.badge}</span> : null}
              </span>
            ),
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
