import { memo, useEffect, useRef } from "react";
import PixelSprite from "../../components/PixelArt/PixelSprite";
import { DOTS, PLUS, SPARKLE } from "../../components/PixelArt/pixelArt";
import { CLOUD_SEA_BACK, CLOUD_SEA_FRONT, SKY_CLOUDS } from "../../components/PixelArt/pixelScenery";
import {
  BLUE_PALETTE as BLUE,
  DOT_PALETTE,
  GOLD_PALETTE as GOLD,
  SEA_BACK_PALETTE,
  SEA_FRONT_PALETTE,
  SKY_CLOUD_PALETTE,
} from "./palettes";
import styles from "./PageShell.module.scss";

/* 背景雲：位置用視窗百分比，depth 越大跟游標視差移得越多（越近） */
const CLOUDS = [
  { rows: SKY_CLOUDS.c, cell: 6, left: "3%", top: "9%", depth: 0.35, drift: "driftA" },
  { rows: SKY_CLOUDS.b, cell: 6, left: "40%", top: "4%", depth: 0.2, drift: "driftB" },
  { rows: SKY_CLOUDS.a, cell: 7, left: "76%", top: "14%", depth: 0.5, drift: "driftB" },
  { rows: SKY_CLOUDS.d, cell: 6, left: "58%", top: "30%", depth: 0.25, drift: "driftA" },
  { rows: SKY_CLOUDS.b, cell: 5, left: "12%", top: "58%", depth: 0.3, drift: "driftB" },
];

const STARS = [
  { rows: PLUS, palette: GOLD, cell: 5, left: "34%", top: "13%" },
  { rows: SPARKLE, palette: GOLD, cell: 4, left: "91%", top: "7%" },
  { rows: PLUS, palette: BLUE, cell: 4, left: "6%", top: "40%" },
  { rows: SPARKLE, palette: BLUE, cell: 3, left: "52%", top: "20%", wideOnly: true },
  { rows: PLUS, palette: GOLD, cell: 4, left: "88%", top: "62%" },
  { rows: PLUS, palette: BLUE, cell: 4, left: "47%", top: "78%", wideOnly: true },
];

/**
 * 像素天空：柔和雲（慢慢飄、跟游標有一點視差）、金藍十字星（閃爍）、點點方陣與底部雲海。
 * 深色模式換成夜空配色並多一層小星點。整層純裝飾，減少動態效果時全部靜止。
 */
function PixelSky() {
  const rootRef = useRef(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return undefined;
    let raf = 0;
    let target = { x: 0, y: 0 };
    const apply = () => {
      raf = 0;
      root.style.setProperty("--sky-px", target.x.toFixed(3));
      root.style.setProperty("--sky-py", target.y.toFixed(3));
    };
    const onMove = (e) => {
      target = {
        x: (e.clientX / window.innerWidth) * 2 - 1,
        y: (e.clientY / window.innerHeight) * 2 - 1,
      };
      if (!raf) raf = window.requestAnimationFrame(apply);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className={styles.sky} ref={rootRef} aria-hidden="true">
      <div className={styles.nightStars} />
      {CLOUDS.map((c, i) => (
        <div
          key={i}
          className={styles.skyItem}
          style={{ left: c.left, top: c.top, "--depth": c.depth }}
        >
          <PixelSprite className={`${styles.skyCloud} ${styles[c.drift]}`} rows={c.rows} palette={SKY_CLOUD_PALETTE} cell={c.cell} />
        </div>
      ))}
      {STARS.map((s, i) => (
        <div
          key={`s${i}`}
          className={`${styles.skyItem} ${s.wideOnly ? styles.wideOnly : ""}`}
          style={{ left: s.left, top: s.top, "--depth": 0.15, "--twinkle-delay": `${i * -0.7}s` }}
        >
          <PixelSprite className={styles.skyStar} rows={s.rows} palette={s.palette} cell={s.cell} />
        </div>
      ))}
      <PixelSprite className={`${styles.skyDots} ${styles.skyDotsTop}`} rows={DOTS} palette={DOT_PALETTE} cell={6} />
      <PixelSprite className={`${styles.skyDots} ${styles.skyDotsBottom}`} rows={DOTS} palette={DOT_PALETTE} cell={6} />
      <div className={styles.sea}>
        <PixelSprite className={styles.seaBack} rows={CLOUD_SEA_BACK} palette={SEA_BACK_PALETTE} cell={8} />
        <PixelSprite className={styles.seaFront} rows={CLOUD_SEA_FRONT} palette={SEA_FRONT_PALETTE} cell={8} />
      </div>
    </div>
  );
}

/* 沒有 props：外框換心情重繪時不必跟著重算雲海 */
export default memo(PixelSky);
