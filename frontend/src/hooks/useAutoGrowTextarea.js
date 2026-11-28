import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

/**
 * 聊天輸入框隨內容長高：從 rows 的高度開始，到 CSS max-height 就停，之後才在框內捲動。
 *
 * 還沒到上限前一律 overflow-y: hidden，超過才換成 auto。scrollHeight 是整數、內容實際高度
 * 有小數（行高 1.45），瀏覽器縮放 90% 這類倍率下框會比內容矮不到 1px；這時若是 auto 就會冒出捲軸，
 * 字被擠到下一行、寬度一變又重新量，輸入框在一行和兩行之間不停跳動。
 * 量之前也先關掉捲軸，量到的永遠是「沒有捲軸」時的換行，結果不受上一次狀態影響。
 *
 * 寬度跟上次量高度時不同（拖拉欄寬、縮放視窗、從隱藏變成看得到、面板展開動畫還沒跑完就先量了）
 * 就重新量。比的是含框寬度（offsetWidth），輸入框自己的捲軸出現或消失不算寬度改變。
 *
 * @param {{ current: HTMLTextAreaElement | null }} ref textarea 的 ref
 * @param {string} value 目前內容，變了就重新量
 * @param {boolean} [active=true] textarea 在畫面上時才量（例如助手面板打開時）
 */
export default function useAutoGrowTextarea(ref, value, active = true) {
  const measuredWidthRef = useRef(null);

  const resize = useCallback(() => {
    const textarea = ref.current;
    // 看不見的時候（所在分頁隱藏、面板沒開）量到的高度是 0，等看得到再量
    if (!textarea || textarea.offsetParent === null) return;
    textarea.style.overflowY = "hidden";
    textarea.style.height = "auto";
    const needed = textarea.scrollHeight;
    textarea.style.height = `${needed}px`;
    const max = Number.parseFloat(window.getComputedStyle(textarea).maxHeight);
    if (needed > max) textarea.style.overflowY = "auto";
    measuredWidthRef.current = textarea.offsetWidth;
  }, [ref]);

  useLayoutEffect(() => {
    if (active) resize();
  }, [value, active, resize]);

  useEffect(() => {
    const textarea = ref.current;
    if (!active || !textarea || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      if (textarea.offsetWidth !== measuredWidthRef.current) resize();
    });
    observer.observe(textarea);
    return () => observer.disconnect();
  }, [active, ref, resize]);
}
