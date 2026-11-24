import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import OctoPet from "../../../components/OctoPet/OctoPet";
import PixelSprite from "../../../components/PixelArt/PixelSprite";
import { BOOK, PLUS, SPARKLE, WORDMARK } from "../../../components/PixelArt/pixelArt";
import { OctoMoodContext, restingMood } from "./octoMood";
import PixelSky from "./PixelSky";
import { HERO_CLOUD } from "../../../components/PixelArt/pixelScenery";
import styles from "./PixelPageShell.module.scss";

const CLOUD_PALETTE = {
  o: "var(--px-cloud-line)",
  f: "var(--px-cloud-fill)",
  h: "var(--px-cloud-hi)",
  s: "var(--px-cloud-shade)",
};
const BOOK_PALETTE = {
  g: "var(--px-book-line)",
  a: "var(--px-cloud-line)",
  c: "var(--px-book-page)",
  b: "var(--px-book-shade)",
  d: "var(--px-gold)",
  j: "var(--px-gold-dark)",
};
const WORDMARK_PALETTE = { t: "var(--px-word-top)", b: "var(--px-word-bottom)" };
const GOLD = { x: "var(--px-gold)", X: "var(--px-gold-hi)" };

/* 心情 → 章魚的動作；出錯、被戳的反應過一下自己回到待機 */
const ACTIVITY = { idle: "idle", shy: "shy", thinking: "thinking", error: "error", done: "done", poke: "done" };
const SETTLE_MS = { error: 2800, poke: 1500 };
const POKE_LINES = 3;

/* 每格幾 px：跟著視窗寬度走，一律整數，像素才不會糊 */
const CELL_STEPS = [
  [1800, 8],
  [1400, 7],
  [1200, 6],
  [1024, 5],
  [0, 4],
];
function pickCell() {
  if (typeof window === "undefined") return 6;
  return CELL_STEPS.find(([min]) => window.innerWidth >= min)[1];
}
function usePixelCell() {
  const [cell, setCell] = useState(pickCell);
  useEffect(() => {
    const onResize = () => setCell(pickCell());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return cell;
}

/**
 * 像素風登入頁外框（預覽中，尚未取代 PageShell）：
 * 寬螢幕左右分欄——左邊章魚學士坐在書上、背後一朵像素雲，會對表單的動作有反應；右邊是登入卡。
 * 窄螢幕（< 1024px）收成置中單卡，章魚與字標縮小放在卡片上方。
 */
export default function PixelPageShell({ children }) {
  const { t } = useTranslation("login");
  const cell = usePixelCell();
  const [mood, setMood] = useState("idle");
  const [scene, setScene] = useState("login");
  const [pokeCount, setPokeCount] = useState(0);
  const timerRef = useRef(0);

  /* 出錯、被戳之後幾秒回到待機（焦點還在密碼欄就繼續擋臉）；換成別的心情就取消 */
  useEffect(() => {
    window.clearTimeout(timerRef.current);
    const ms = SETTLE_MS[mood];
    if (ms) timerRef.current = window.setTimeout(() => setMood(restingMood()), ms);
    return () => window.clearTimeout(timerRef.current);
  }, [mood, pokeCount]);

  /* 換畫面時心情歸零：上一個畫面留下的「成功了！」不會帶到下一個畫面 */
  const sceneRef = useRef(scene);
  const changeScene = useCallback((next) => {
    if (sceneRef.current === next) return;
    sceneRef.current = next;
    setScene(next);
    setMood(restingMood());
  }, []);

  const context = useMemo(() => ({ setMood, setScene: changeScene }), [changeScene]);

  const poke = () => {
    if (mood !== "idle" && mood !== "poke") return;
    setPokeCount((n) => n + 1);
    setMood("poke");
  };

  const line =
    mood === "idle"
      ? t(`PixelLogin.say.${scene}`)
      : mood === "poke"
        ? t(`PixelLogin.poke.${(pokeCount - 1) % POKE_LINES}`)
        : t(`PixelLogin.say.${mood}`);

  return (
    <OctoMoodContext.Provider value={context}>
      <div className={styles.page} data-mood={mood}>
        <PixelSky />
        <div className={styles.layout}>
          <section className={styles.hero} style={{ "--cell": `${cell}px` }}>
            <div className={styles.stage}>
              <PixelSprite className={styles.stageCloud} rows={HERO_CLOUD} palette={CLOUD_PALETTE} />
              <PixelSprite className={`${styles.stageStar} ${styles.stageStarLeft}`} rows={PLUS} palette={GOLD} />
              <PixelSprite className={`${styles.stageStar} ${styles.stageStarRight}`} rows={SPARKLE} palette={GOLD} />
              <PixelSprite className={styles.stageBook} rows={BOOK} palette={BOOK_PALETTE} />
              <button
                type="button"
                className={styles.octoButton}
                onClick={poke}
                aria-label={t("PixelLogin.octoLabel")}
              >
                <OctoPet activity={ACTIVITY[mood]} scale={cell} bubble={false} />
              </button>
              {/* 對話泡泡只是陪襯（錯誤訊息照樣在表單裡），不給讀屏重複唸 */}
              <p key={`${mood}-${scene}-${pokeCount}`} className={styles.bubble} aria-hidden="true">
                {line}
                <i />
              </p>
            </div>
            <PixelSprite className={styles.wordmark} rows={WORDMARK} palette={WORDMARK_PALETTE} label="SkyLab" />
            <p className={styles.tagline}>{t("PixelLogin.heroTagline")}</p>
            <p className={styles.heroSub}>{t("PixelLogin.heroSub")}</p>
          </section>
          <main className={styles.cardWrap}>
            <div className={styles.card}>{children}</div>
          </main>
        </div>
      </div>
    </OctoMoodContext.Provider>
  );
}
