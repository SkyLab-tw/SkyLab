import { createContext } from "react";

/**
 * 版面層級的共用能力。
 *
 * 單獨放一個檔案而不是掛在 DashboardLayout 上：只想拿 context 的元件
 * （AI 助手、表單頁）不該因此把整棵版面樹一起載進來。
 */
export const LayoutContext = createContext({
  setCompactFooter: () => {},
  /* 頁面自己有對話欄（AI 導師檢查的檢查助理）時設成 true：AI 助手改用覆蓋層開啟，
     不跟頁面並排擠窄版面，也不會出現兩個對話框並排、不知道該問哪一個 */
  setAssistantOverlay: () => {},
  /* 申請表單掛載時把自己註冊進來，AI 助手才能就地把欄位填好，
     並且拿得到表單當下的真實候選（該時段的 GPU、時段選項、作業系統清單）。 */
  registerRequestForm: () => {},
  requestForm: null,
  reportRequestSubmission: () => {},
  requestSubmission: null,
  /* 畫面說明用：頁面掛載時把自己註冊進來，助手才拿得到欄位當下的值與驗證錯誤。
     沒有註冊的頁面照樣能被問「這頁在做什麼」——那部分只需要伺服器端的靜態定義。 */
  registerSurface: () => {},
  surface: null,
});
