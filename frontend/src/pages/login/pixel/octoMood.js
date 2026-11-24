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

/** 密碼欄外層用：聚焦時章魚舉書不偷看，離開就放下 */
export function useShyHandlers() {
  const { setMood } = useOctoMood();
  return {
    onFocus: () => setMood("shy"),
    onBlur: () => setMood((current) => (current === "shy" ? "idle" : current)),
  };
}
