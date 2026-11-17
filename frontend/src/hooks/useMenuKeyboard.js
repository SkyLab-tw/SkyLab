import { useEffect } from "react";

/**
 * 錨定選單的鍵盤操作（ActionMenu、ListboxPopover、PowerMenu 共用，定位另見 useAnchoredMenu）：
 * - 量好位置、看得到之後把焦點移進選單（隱形時 focus 會讓頁面捲到左上角）：
 *   initialSelector 找得到就放那裡（單選清單的目前選項），否則放第一個可用項目。
 * - 上下鍵、Home／End 在可用項目間移動；wrap 為 true 時頭尾相接（動作選單），
 *   false 停在頭尾（單選清單，跟原生下拉一樣）。
 * - Esc、Tab 把焦點交回觸發鈕：Esc 的關閉由 useAnchoredMenu 在 document 上處理並標成已處理；
 *   Tab 在這裡關閉、不攔預設行為，焦點會從觸發鈕繼續往下一個元素走。
 *
 * 回傳 onKeyDown，掛在選單元素上。closing（離場動畫期間）時不再接受操作。
 */
export default function useMenuKeyboard({
  ref,
  anchorRef,
  onClose,
  positioned,
  closing = false,
  itemSelector,
  initialSelector,
  wrap = true,
}) {
  useEffect(() => {
    if (!positioned) return;
    const menu = ref.current;
    const target = (initialSelector && menu?.querySelector(initialSelector)) || menu?.querySelector(itemSelector);
    target?.focus({ preventScroll: true });
  }, [positioned, ref, itemSelector, initialSelector]);

  return function handleKeyDown(event) {
    if (closing) return;
    if (event.key === "Escape" || event.key === "Tab") {
      anchorRef?.current?.focus();
      if (event.key === "Tab") onClose();
      return;
    }
    const items = [...(ref.current?.querySelectorAll(itemSelector) ?? [])];
    if (!items.length) return;
    const current = items.indexOf(document.activeElement);
    const last = items.length - 1;
    const nextIndex = {
      ArrowDown: current < 0 ? 0 : current === last ? (wrap ? 0 : last) : current + 1,
      ArrowUp: current < 0 ? last : current === 0 ? (wrap ? last : 0) : current - 1,
      Home: 0,
      End: last,
    }[event.key];
    if (nextIndex === undefined) return;
    event.preventDefault();
    items[nextIndex].focus();
    items[nextIndex].scrollIntoView?.({ block: "nearest" });
  };
}
