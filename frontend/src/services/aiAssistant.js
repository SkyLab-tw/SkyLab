import { apiGet, apiPostEventStream } from "./api";

const BASE = "/api/v1/ai/assistant";

/* 等回應開始的上限。回應是逐段送來的，正常情況標頭馬上就回來；中間有代理把整段
   回應攢起來才放行時，要等到助手讀完說明、想過、檢查完，預設的 15 秒不夠。 */
export const AI_ASSISTANT_TIMEOUT_MS = 120_000;

/* 後端收得下的上限，超過會直接 422，重按幾次都一樣，所以送出前先裁好 */
export const MAX_ASSISTANT_MESSAGES = 24;
export const MAX_ASSISTANT_MESSAGE_CHARS = 4000;
const MAX_PATH_CHARS = 300;
const MAX_GUIDE_STEPS = 20;
const MAX_STATE_ELEMENTS = 60;

const LOCALES = ["zh-TW", "en", "ja"];

/** 介面語言對應到後端認得的三種；助手用它決定回覆語言。 */
export function assistantLocale(language) {
  const value = String(language ?? "");
  if (LOCALES.includes(value)) return value;
  const prefix = value.toLowerCase().split("-")[0];
  if (prefix === "zh") return "zh-TW";
  return LOCALES.find((item) => item === prefix) ?? "zh-TW";
}

/**
 * 把對話整理成後端收得下的樣子。
 *
 * 只留 user／assistant 的文字；連續同一個角色的併成一則（失敗的那一輪沒有回覆，
 * 會留下兩則相連的 user，有些模型的對話範本不接受）；開頭一定是 user；只留最近的
 * 幾則，每則截到上限。最後一則不是 user 就代表沒有東西可問，回空陣列。
 */
export function normalizeAssistantMessages(messages) {
  const merged = [];
  for (const message of messages ?? []) {
    if (message?.role !== "user" && message?.role !== "assistant") continue;
    const content = String(message.content ?? "").trim();
    if (!content) continue;
    const last = merged[merged.length - 1];
    if (last?.role === message.role) last.content = `${last.content}\n\n${content}`;
    else merged.push({ role: message.role, content });
  }
  if (merged[merged.length - 1]?.role !== "user") return [];
  const recent = merged.slice(-MAX_ASSISTANT_MESSAGES);
  while (recent.length && recent[0].role !== "user") recent.shift();
  return recent.map((message) => ({
    role: message.role,
    content: message.content.slice(0, MAX_ASSISTANT_MESSAGE_CHARS),
  }));
}

/* 後端的欄位狀態只收字串與布林，而且有長度上限。頁面回報的值可能是數字（範本 id、核心數）
   或 null，這裡統一轉好，免得整個請求因為一個欄位的型別被 422 擋掉。 */
function text(value, limit) {
  return value == null || value === "" ? null : String(value).slice(0, limit);
}

function normalizeElementState(raw = {}) {
  const state = {};
  const value = text(raw.value, 500);
  const error = text(raw.error, 300);
  const reason = text(raw.disabled_reason, 300);
  if (value !== null) state.value = value;
  if (error !== null) state.error = error;
  if (typeof raw.disabled === "boolean") state.disabled = raw.disabled;
  if (reason !== null) state.disabled_reason = reason;
  return state;
}

function normalizeScreen(screen = {}) {
  const state = Object.fromEntries(
    Object.entries(screen.state ?? {})
      .slice(0, MAX_STATE_ELEMENTS)
      .map(([id, value]) => [id, normalizeElementState(value ?? {})]),
  );
  return {
    path: String(screen.path ?? "/").slice(0, MAX_PATH_CHARS),
    surface_id: screen.surfaceId ?? null,
    active_target: screen.activeTarget ?? null,
    state,
    guide_steps: (screen.guideSteps ?? [])
      .filter((step) => step?.id != null && step?.title)
      .slice(0, MAX_GUIDE_STEPS)
      // 後端對 id 與標題都有長度上限，超過整個請求會被 422 擋掉
      .map((step) => ({ id: String(step.id).slice(0, 40), title: String(step.title).slice(0, 120) })),
  };
}

/** 畫面清單只跟身分有關，一次對話期間不會變，載一次就好。 */
let surfacesPromise = null;

export const AiAssistantService = {
  /**
   * 目前身分看得到的畫面清單（id / path / title / purpose / when_to_use / has_fields）。
   * 用來把 react-router 的路徑對應成 surface_id，以及顯示「正在查看哪一頁」。
   */
  surfaces() {
    if (!surfacesPromise) {
      surfacesPromise = apiGet(`${BASE}/surfaces`).catch((error) => {
        surfacesPromise = null; // 失敗不要卡住之後的嘗試
        throw error;
      });
    }
    return surfacesPromise;
  },

  /** 登出或換身分時清掉快取，免得看到上一個帳號的畫面清單。 */
  resetSurfaces() {
    surfacesPromise = null;
  },

  /**
   * 助手的一輪對話。每一句話都走這裡——要找頁面、問怎麼做、問眼前的欄位、要規劃機器，
   * 由後端的模型自己判斷，前端不分流。
   *
   * @param {{messages: {role: "user"|"assistant", content: string}[], locale?: string,
   *   screen?: {path?: string, surfaceId?: string|null, activeTarget?: string|null,
   *     state?: Record<string, object>, guideSteps?: {id: string, title: string}[]}}} input
   *   messages 是到這一輪為止的對話（伺服器端沒有會話表，由前端保存），最後一則是這次的問題。
   *   screen 是使用者眼前的畫面：路徑、頁面註冊的欄位狀態，以及聚光燈現在指得到的步驟。
   * @param {(event: {type: "delta", text: string} | {type: "reset"} | {type: "status", tool: string}) => void} [input.onEvent]
   *   回答產生的過程：delta 是正在寫的字（接在已顯示的後面）、reset 代表先前的字作廢、
   *   status 代表助手剛用完某個工具還要再想一輪。這些只是讓人不必乾等——回答要寫完才能
   *   檢查，算數的是 resolve 回來的那一份，畫面要用它換掉過程中顯示的字。
   * @returns {Promise<{request_id: string, reply: string,
   *   pages: {title: string, path: string, reason: string, state: object|null}[],
   *   flow: {flow_id: string, title: string, steps: object[]}|null,
   *   plan: {status: "ask"|"ready", facts: object, question: object|null, answered: number, total: number}|null,
   *   spotlight: {target_id: string}|null, choices: string[], degraded: boolean}>}
   *   頁面按鈕、流程卡與選項都由伺服器依權限組好；degraded 代表模型不可用，reply 是固定說明。
   */
  async chat({ messages, locale, screen, onEvent } = {}) {
    let final = null;
    await apiPostEventStream(
      `${BASE}/chat`,
      {
        messages: normalizeAssistantMessages(messages),
        locale: assistantLocale(locale),
        screen: normalizeScreen(screen),
      },
      {
        timeoutMs: AI_ASSISTANT_TIMEOUT_MS,
        onEvent: ({ event, data }) => {
          if (event === "final") final = data;
          else if (["delta", "reset", "status"].includes(event)) onEvent?.({ type: event, ...data });
        },
      },
    );
    /* 伺服器處理到一半出錯（error 事件）或連線提早結束，都不會有 final */
    if (!final) throw { status: 502, message: "Assistant stream ended without a response" };
    return final;
  },
};

/**
 * 路徑對應到 surface。
 *
 * 先找完全相同的路徑；沒有才比對帶參數的樣板（/my-resources/:vmid）。同一個
 * 路徑可能有多個畫面（/my-requests 同時是列表與表單），那種情況要由頁面自己
 * 註冊來決定是哪一個，這裡只回最後的預設值。
 */
export function matchSurface(surfaces, path) {
  if (!Array.isArray(surfaces) || !path) return null;
  const clean = path.split("?")[0].replace(/\/+$/, "") || "/";

  const exact = surfaces.find((surface) => surface.path === clean);
  if (exact) return exact;

  const segments = clean.split("/");
  return (
    surfaces.find((surface) => {
      const parts = surface.path.split("/");
      if (parts.length !== segments.length) return false;
      return parts.every(
        (part, index) => part.startsWith(":") || part === segments[index],
      );
    }) ?? null
  );
}
