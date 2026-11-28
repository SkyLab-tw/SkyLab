import styles from "./Collapse.module.scss";

/**
 * Collapse — 展開／收合時高度平滑過渡、內容同時淡入淡出。
 * 開關由外面決定（標題列的收合鈕、「預覽」晶片之類），這裡只負責動畫：
 * grid-template-rows 0fr↔1fr 讓高度跟著內容走（不必量高度），收合後內容仍掛著、但 inert（點不到、Tab 不進去、讀屏略過）。
 *
 * - 放在有 gap 的 flex 欄裡時傳 gap（px）：收合時用負的 margin-top 抵掉那段 gap，下面的內容才會貼上來、不留空隙。
 * - 內容四周預留 4px 不裁切，貼邊按鈕的焦點框（outline-offset 2px）才不會被切掉。
 * - 使用者設定減少動態效果時直接切換，不播動畫。
 *
 * @param {boolean} open 是否展開
 * @param {number} gap 所在 flex 欄的 gap（px），沒有就不傳
 * @param {string} className 外框額外樣式
 * @param {string} innerClassName 內容區額外樣式（排版、間距）
 * @param ref 外框（例如展開後要 scrollIntoView）
 * 其餘屬性（id、data-guide）掛在外框上；aria-controls 指向這裡的 id
 */
export default function Collapse({ ref, open, gap = 0, className = "", innerClassName = "", style, children, ...rest }) {
  return (
    <div
      ref={ref}
      className={`${styles.collapse} ${open ? styles.open : ""} ${className}`}
      style={gap ? { "--collapse-gap": `${gap}px`, ...style } : style}
      inert={!open}
      {...rest}
    >
      <div className={`${styles.inner} ${innerClassName}`}>{children}</div>
    </div>
  );
}
