import { createContext, useContext, useEffect } from "react";

/**
 * 像素登入頁的章魚心情：表單裡的動作（輸入密碼、送出、出錯）回報給左側的章魚學士。
 * context 獨立成檔：元件檔混輸出 context 會讓 Vite 熱更新失效（見 vite-fast-refresh）。
 *
 * mood：idle 待機／shy 輸入密碼時舉書擋臉／thinking 送出中／error 出錯／done 成功
 * scene：目前是哪個畫面（login、forgot、register、reset、totp、device），決定待機時的招呼語
 */
export const OctoMoodContext = createContext({ setMood() {}, setScene() {} });

export function useOctoMood() {
  return useContext(OctoMoodContext);
}

/** 畫面掛上時告訴章魚現在是哪個畫面 */
export function useOctoScene(scene) {
  const { setScene } = useOctoMood();
  useEffect(() => {
    setScene(scene);
  }, [scene, setScene]);
}

/* 密碼欄外層的標記：章魚回到待機時用它判斷焦點是不是還在密碼欄 */
export const SHY_ATTR = "data-octo-shy";

/** 沒事做時該是什麼心情：焦點還在密碼欄就繼續擋臉，不然待機 */
export function restingMood() {
  if (typeof document === "undefined") return "idle";
  return document.activeElement?.closest?.(`[${SHY_ATTR}]`) ? "shy" : "idle";
}

/** 密碼欄外層用：聚焦時章魚舉書不偷看，離開就放下 */
export function useShyHandlers() {
  const { setMood } = useOctoMood();
  return {
    [SHY_ATTR]: "",
    onFocus: () => setMood("shy"),
    onBlur: () => setMood((current) => (current === "shy" ? "idle" : current)),
  };
}
