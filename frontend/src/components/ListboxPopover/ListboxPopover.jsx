import { useEffect } from "react";
import { createPortal } from "react-dom";
import MIcon from "../MIcon";
import useAnchoredMenu from "../../hooks/useAnchoredMenu";
import useMenuKeyboard from "../../hooks/useMenuKeyboard";
import styles from "./ListboxPopover.module.scss";

/** 清單寬度跟觸發鈕一樣寬，但夾在這個範圍內：太窄放不下兩行說明，太寬一列字拉太長 */
export const LISTBOX_MIN_WIDTH = 260;
export const LISTBOX_MAX_WIDTH = 480;
/** 清單最高這麼高，再多就在清單內捲動；下方空間不夠時會再縮，不會往上蓋住觸發鈕 */
export const LISTBOX_MAX_HEIGHT = 420;

const OPTION_SELECTOR = '[role="option"]:not(:disabled)';
const SELECTED_SELECTOR = `${OPTION_SELECTOR}[aria-selected="true"]`;

/**
 * 從觸發鈕往下（放不下就往上）展開的單選清單，例如「換週」；側欄底部的語言選單傳 placement="side"，貼著側欄外緣彈出。
 * 底色一律是 popover-glass（跟側欄彈出、ActionMenu 同一套玻璃，隨介面風格與主題色變）。
 * 跟原生 <select> 的差別是每個選項可以有第二行說明（狀態、日期），選項多時在清單內捲動。
 *
 * - 定位、外點與 Esc 關閉、portal 到 body 共用 useAnchoredMenu，鍵盤操作共用 useMenuKeyboard（同 ActionMenu、PowerMenu）。
 * - 開啟時焦點放在目前選中的那項，並把它捲到清單中間；上下鍵、Home／End 移動，Enter／空白鍵選取。
 * - 選完、按 Esc 或 Tab 時焦點回到觸發鈕；Tab 不攔，焦點會從觸發鈕繼續往下一個元素走，跟原生下拉一樣。
 * - 呼叫端用 useDialogPresence 保留離場動畫：關閉期間傳 closing，清單不再接受操作。
 *
 * options: [{ value, label, description?, disabled? }]，label／description 可以是節點。
 */
export default function ListboxPopover({
  id,
  anchorRef,
  ariaLabel,
  options,
  value,
  onSelect,
  onClose,
  closing = false,
  placement,
}) {
  const anchorWidth = anchorRef?.current?.offsetWidth ?? 0;
  const width = Math.min(LISTBOX_MAX_WIDTH, Math.max(LISTBOX_MIN_WIDTH, anchorWidth));
  const { ref, pos } = useAnchoredMenu({ anchorRef, onClose, width, align: "left", maxHeight: LISTBOX_MAX_HEIGHT, placement });
  const positioned = pos !== null;
  const handleKeyDown = useMenuKeyboard({
    ref,
    anchorRef,
    onClose,
    closing,
    positioned,
    itemSelector: OPTION_SELECTOR,
    initialSelector: SELECTED_SELECTOR,
    wrap: false,
  });

  // 打開時把目前選中的那項捲到清單中間（焦點由 useMenuKeyboard 放上去）
  useEffect(() => {
    if (!positioned) return;
    const list = ref.current;
    const target = list?.querySelector(SELECTED_SELECTOR) ?? list?.querySelector(OPTION_SELECTOR);
    if (!list || !target) return;
    list.scrollTop = Math.max(0, target.offsetTop - (list.clientHeight - target.offsetHeight) / 2);
  }, [positioned, ref]);

  function choose(nextValue) {
    anchorRef?.current?.focus();
    onClose();
    onSelect(nextValue);
  }

  const className = [
    styles.listbox,
    pos?.openUp ? styles.listboxUp : styles.listboxDown,
    closing ? styles.listboxOut : "",
  ].filter(Boolean).join(" ");

  return createPortal(
    <div
      ref={ref}
      id={id}
      role="listbox"
      aria-label={ariaLabel}
      className={className}
      style={pos ? { top: pos.top, left: pos.left, width, maxHeight: pos.maxHeight } : { top: 0, left: 0, width, visibility: "hidden" }}
      onKeyDown={handleKeyDown}
      // portal 的 React 事件仍沿元件樹冒泡，別讓外層可點的列也收到這次點擊
      onClick={(event) => event.stopPropagation()}
    >
      {options.map((option) => {
        const selected = String(option.value) === String(value);
        return (
          <button
            key={option.value}
            type="button"
            role="option"
            aria-selected={selected}
            className={selected ? styles.optionSelected : styles.option}
            disabled={option.disabled}
            tabIndex={-1}
            onClick={() => choose(option.value)}
          >
            <span className={styles.optionText}>
              <span className={styles.optionLabel}>{option.label}</span>
              {option.description && <span className={styles.optionDescription}>{option.description}</span>}
            </span>
            {selected && <MIcon name="check" size={18} className={styles.optionCheck} />}
          </button>
        );
      })}
    </div>,
    document.body,
  );
}
