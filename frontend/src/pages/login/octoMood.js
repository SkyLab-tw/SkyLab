import { createContext, useCallback, useContext, useEffect, useState } from "react";

/**
 * 登入類頁面的章魚心情：表單裡的動作（輸入密碼、送出、出錯）回報給左側的章魚學士。
 * context 獨立成檔：元件檔混輸出 context 會讓 Vite 熱更新失效（見 vite-fast-refresh）。
 *
 * mood：idle 待機／shy 輸入密碼時舉書擋臉／thinking 送出中／error 出錯／done 成功
 * scene：目前是哪個畫面（login、totp、forgot、register、reset、device、enroll、verify），決定待機時的招呼語
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
const SHY_ATTR = "data-octo-shy";

/** 沒事做時該是什麼心情：焦點還在密碼欄就繼續擋臉，不然待機 */
export function restingMood() {
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

/**
 * 表單送出的共用流程：送出中章魚敲筆電、成功跳一下、失敗噴墨並顯示錯誤訊息。
 *
 * run(action, describeError)：describeError 是 err 沒帶訊息時的預設文字，或把 err 轉成文字的函式。
 *   回傳 { ok, result }，呼叫端照 ok 接著做自己的事（切畫面、重置機器人驗證…）。
 * fail(message)：不打後端就知道的錯誤（例如密碼不符規則），一樣讓章魚噴墨。
 * setError(message)：只顯示訊息、不動章魚（例如還沒完成機器人驗證的提醒）。
 */
export function useOctoSubmit() {
  const { setMood } = useOctoMood();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fail = useCallback(
    (message) => {
      setMood("error");
      setError(message);
    },
    [setMood],
  );

  const run = useCallback(
    async (action, describeError) => {
      setError("");
      setLoading(true);
      setMood("thinking");
      try {
        const result = await action();
        setMood("done");
        return { ok: true, result };
      } catch (err) {
        fail(typeof describeError === "function" ? describeError(err) : (err?.message ?? describeError));
        return { ok: false };
      } finally {
        setLoading(false);
      }
    },
    [fail, setMood],
  );

  return { loading, error, setError, fail, run };
}
