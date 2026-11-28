/**
 * AI 助手的對話保存。
 *
 * 放 sessionStorage：重新整理後還在，關掉分頁就沒了，也不會跨分頁或跨裝置。
 * key 帶使用者 id，同一個分頁換帳號登入不會看到上一個人的對話；登出時整批清掉。
 * 儲存空間不可用（隱私模式、配額滿）時安靜地退回「只在記憶體裡」，對話功能不受影響。
 */

const PREFIX = "skylab:ai-assistant:chat:";
const VERSION = 1;

/* 只留最近幾則：再早的內容送不進模型（後端只收最近 24 則），留著只是佔空間 */
export const MAX_STORED_MESSAGES = 40;

const EMPTY = Object.freeze({ messages: [], planned: false });

const keyFor = (userId) => (userId == null || userId === "" ? null : `${PREFIX}${userId}`);

function isMessage(value) {
  return Boolean(value)
    && (value.role === "user" || value.role === "assistant")
    && typeof value.content === "string";
}

/** 讀回這個使用者在這個分頁的對話；沒有、壞掉或版本不合都當作沒有。 */
export function loadAssistantChat(userId) {
  const key = keyFor(userId);
  if (!key) return EMPTY;
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) ?? "null");
    if (stored?.v !== VERSION || !Array.isArray(stored.messages)) return EMPTY;
    return {
      messages: stored.messages.filter(isMessage).slice(-MAX_STORED_MESSAGES),
      planned: Boolean(stored.planned),
    };
  } catch {
    return EMPTY;
  }
}

/** 存下目前的對話；空對話直接刪掉 key，不留一筆空殼。 */
export function saveAssistantChat(userId, { messages = [], planned = false } = {}) {
  const key = keyFor(userId);
  if (!key) return;
  try {
    if (!messages.length) {
      sessionStorage.removeItem(key);
      return;
    }
    sessionStorage.setItem(key, JSON.stringify({
      v: VERSION,
      messages: messages.slice(-MAX_STORED_MESSAGES),
      planned: Boolean(planned),
    }));
  } catch {
    /* 存不進去就只留在記憶體裡 */
  }
}

/** 登出或換帳號時呼叫：清掉這個分頁裡所有帳號的助手對話。 */
export function clearAssistantChats() {
  try {
    const keys = [];
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(PREFIX)) keys.push(key);
    }
    keys.forEach((key) => sessionStorage.removeItem(key));
  } catch {
    /* 沒有儲存空間就沒有東西要清 */
  }
}
