import { gridSize, rowsToPaths } from "./pixelArt";

/**
 * 把字元格畫成像素 SVG（crispEdges，放大不糊）。
 *
 * @param {string[]} rows    字元格，見 pixelArt.js
 * @param {Record<string, string>} palette 字元 → 顏色（建議用 CSS 變數，深色模式才換得了）
 * @param {number} cell      每格幾 px；不給就由外層 CSS 決定寬高
 * @param {string} [label]   無障礙名稱；不給就是純裝飾
 */
export default function PixelSprite({ rows, palette, cell, label, className = "", style }) {
  const { w, h } = gridSize(rows);
  const paths = rowsToPaths(rows);
  return (
    <svg
      className={className}
      viewBox={`0 0 ${w} ${h}`}
      width={cell ? w * cell : undefined}
      height={cell ? h * cell : undefined}
      shapeRendering="crispEdges"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : "true"}
      focusable="false"
      style={style}
    >
      {Object.entries(paths).map(([ch, d]) =>
        palette[ch] ? <path key={ch} d={d} style={{ fill: palette[ch] }} /> : null,
      )}
    </svg>
  );
}
