import { useLayoutEffect, useState } from "react";

/**
 * 量元素目前的寬度，元素尺寸變了就更新（ResizeObserver）。
 * 還沒量到、量到 0（測試環境沒有版面）或瀏覽器沒有 ResizeObserver 時回傳 null，
 * 呼叫端把 null 當成「不知道」，照寬版畫。
 * 用 layout effect 量：第一次畫面出來前就能換成窄版，不會先閃一下寬版。
 */
export default function useElementWidth(ref) {
  const [width, setWidth] = useState(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const update = () => {
      const next = element.getBoundingClientRect().width;
      setWidth(next > 0 ? next : null);
    };
    update();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return width;
}
