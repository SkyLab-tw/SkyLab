import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import OctoPet from "../../components/OctoPet/OctoPet";
import PixelSprite from "../../components/PixelArt/PixelSprite";
import { BOOK, PLUS, SPARKLE, WORDMARK } from "../../components/PixelArt/pixelArt";
import { HERO_CLOUD } from "../../components/PixelArt/pixelScenery";
import { OctoMoodContext, restingMood } from "./octoMood";
import { BOOK_PALETTE, CLOUD_PALETTE, GOLD_PALETTE, WORDMARK_PALETTE } from "./palettes";
import PixelSky from "./PixelSky";
import styles from "./PageShell.module.scss";

/* 出錯、被戳的反應過一下自己回到待機 */
const SETTLE_MS = { error: 2800, poke: 1500 };
/* 被戳時輪流說的話有幾句（語系檔的 PixelLogin.poke.0 … n-1） */
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
 * 登入類頁面的外框（登入各畫面、強制綁定兩步驟驗證、註冊與換信箱的驗證頁共用）：
 * 寬螢幕左右分欄——左邊章魚學士坐在書上、背後一朵像素雲，會對表單的動作有反應；右邊是卡片。
 * 窄螢幕（< 1024px）收成置中單卡，章魚與字標縮小放在卡片上方。
 *
 * @param {string} [scene] 一開始是哪個畫面（決定章魚的招呼語）；裡面的畫面可以再用 useOctoScene 換
 * @param {boolean} [wide] 卡片放寬到 520px（放得下 QR code 與步驟說明）
 */
export default function PageShell({ children, scene: initialScene = "login", wide = false }) {
  const { t } = useTranslation("login");
  const cell = usePixelCell();
  const [mood, setMood] = useState("idle");
  const [scene, setScene] = useState(initialScene);
  const [pokeCount, setPokeCount] = useState(0);

  /* 出錯、被戳之後幾秒回到待機（焦點還在密碼欄就繼續擋臉）；換成別的心情就取消。
     pokeCount 也是依賴：連戳時每一下都重新計時 */
  useEffect(() => {
    const ms = SETTLE_MS[mood];
    if (!ms) return undefined;
    const timer = window.setTimeout(() => setMood(restingMood()), ms);
    return () => window.clearTimeout(timer);
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
      <div className={styles.page}>
        <PixelSky />
        <div className={wide ? `${styles.layout} ${styles.layoutWide}` : styles.layout}>
          <section className={styles.hero} style={{ "--cell": `${cell}px` }}>
            <div className={styles.stage}>
              <PixelSprite className={styles.stageCloud} rows={HERO_CLOUD} palette={CLOUD_PALETTE} />
              <PixelSprite className={`${styles.stageStar} ${styles.stagePlus}`} rows={PLUS} palette={GOLD_PALETTE} />
              <PixelSprite className={`${styles.stageStar} ${styles.stageSparkle}`} rows={SPARKLE} palette={GOLD_PALETTE} />
              <PixelSprite className={styles.stageBook} rows={BOOK} palette={BOOK_PALETTE} />
              <button
                type="button"
                className={styles.octoButton}
                onClick={poke}
                aria-label={t("PixelLogin.octoLabel")}
              >
                {/* 被戳的反應借用「成功」的跳一下 */}
                <OctoPet activity={mood === "poke" ? "done" : mood} scale={cell} bubble={false} />
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
