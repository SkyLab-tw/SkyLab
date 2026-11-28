/* AI 助手對話用到的純函式：送給模型的歷史、送給規劃器的需求、失敗時的說法，
   以及教學環境分頁的網址。助手本身不分流、不記任務狀態——那些交給後端的模型。 */

/* ── 送給助手的歷史 ───────────────────────────────────────────────── */

/**
 * 回覆下方附了哪些卡片，用一行字記進歷史。
 * 卡片是畫面上的東西，模型下一輪看不到；不寫下來的話「第二步是什麼」這種追問沒有東西可指。
 */
export function cardNote({ pages = [], flow = null } = {}) {
  const parts = [];
  if (flow?.steps?.length) {
    parts.push(`流程「${flow.title}」：${flow.steps.map((step) => step.title).join("→")}`);
  }
  if (pages.length) parts.push(`頁面按鈕：${pages.map((page) => page.title).join("、")}`);
  return parts.length ? `（已附上${parts.join("；")}）` : "";
}

/**
 * 畫面上的訊息 → 送給後端的 { role, content }。
 * 本機產生的錯誤訊息（omit）不送：那不是助手說的話，送了只會讓模型跟著道歉。
 */
export function historyForAssistant(messages) {
  return (messages ?? [])
    .filter((message) => !message.omit)
    .map((message) => ({
      role: message.role,
      content: message.note ? `${message.content}\n${message.note}` : message.content,
    }));
}

/* ── 回答產生的過程 ───────────────────────────────────────────────── */

/**
 * 回答還在寫的時候，畫面上暫時顯示的東西：{ text, tool }。
 * text 是到目前為止寫出來的字；tool 是助手剛用完的工具（還沒有字的時候，用來說明它正在做什麼）。
 * 這些都不算數——回答要寫完才能檢查，最後由完整的回應取代。
 */
export function applyStreamEvent(state, event) {
  const current = state ?? { text: "", tool: null };
  if (event?.type === "delta") return { ...current, text: current.text + String(event.text ?? "") };
  if (event?.type === "reset") return { ...current, text: "" };
  if (event?.type === "status") return { ...current, tool: event.tool ?? null };
  return current;
}

const STREAM_STATUS_KEYS = {
  read_help: "AiFloatingChat.statusReadHelp",
  get_my_requests: "AiFloatingChat.statusMyRequests",
};

/** 等待時顯示的那一行字。還沒用過工具就不說（只有章魚在敲筆電）。 */
export function streamStatusKey(tool) {
  if (!tool) return null;
  return STREAM_STATUS_KEYS[tool] ?? "AiFloatingChat.statusWriting";
}

/* ── 送給規劃器的需求 ─────────────────────────────────────────────── */

/* 後端一次最多收 50 則、32K 字；長對話整段送過去會直接 400，重按幾次都一樣。
   只送最近的幾則——規劃需要的答案已經在 facts 裡，不靠舊訊息。
   最新一則本身就超長（貼了一大段）時截斷它，不能因為「至少要留一則」就整則送出。 */
export function recentMessages(history, { maxMessages = 12, maxChars = 12_000 } = {}) {
  const kept = [];
  let chars = 0;
  for (const message of [...history].reverse()) {
    if (kept.length >= maxMessages) break;
    const content = String(message.content ?? "");
    if (!kept.length && content.length > maxChars) {
      kept.unshift({ ...message, content: content.slice(0, maxChars) });
      break;
    }
    if (chars + content.length > maxChars) break;
    kept.unshift(message);
    chars += content.length;
  }
  return kept;
}

const FACT_KEYS = ["purpose", "gpu", "display", "duration"];
const FACT_LABELS = { purpose: "用途", gpu: "加速需求", display: "作業環境", duration: "使用時間" };
/* 每一格都有上限，加上 recentMessages 的 12K 字，總長才穩定低於後端的 32K。 */
const FACT_CHARS = 500;

/** 助手問到的需求，原樣交給規劃器判斷，不要讓它從文字裡猜。沒有任何一格就回 null。 */
export function intakeFactsPayload(facts) {
  if (!facts || !FACT_KEYS.some((key) => facts[key])) return null;
  return {
    ...Object.fromEntries(FACT_KEYS.map((key) => [key, facts[key] ? String(facts[key]) : null])),
    inferred: (facts.inferred ?? []).filter((key) => FACT_KEYS.includes(key)),
  };
}

/**
 * 規劃器要的對話：最近幾則，最後補一則把需求講清楚的使用者訊息。
 * 規劃器除了結構化的 facts 也會讀文字找線索，而對話的最後一句常常只是「好」或某個選項，
 * 所以需求再用文字寫一次；推斷出來的那幾格標成可調整，跟使用者明講的分開。
 */
export function planRequestMessages(history, facts) {
  const recent = recentMessages(history ?? []);
  const lines = FACT_KEYS.flatMap((key) => {
    const value = facts?.[key];
    if (!value) return [];
    const source = facts.inferred?.includes(key) ? "建議預設，可調整" : "使用者已提供";
    return [`${FACT_LABELS[key]}（${source}）：${String(value).slice(0, FACT_CHARS)}`];
  });
  if (!lines.length) return recent;
  return [...recent, { role: "user", content: `請依這些需求規劃配置：\n${lines.join("\n")}` }];
}

/* ── 失敗時的說法 ─────────────────────────────────────────────────── */

/* 規劃失敗的原因不同，使用者能做的事也不同：逾時可以重試、太頻繁要等、
   對話太長要開新對話。全部說成「已保留你的需求」只會讓人一直按重試。 */
export function planErrorKey(error) {
  if (error?.timeout || error?.status === 408) return "AiFloatingChat.planTimedOut";
  if (error?.status === 429) return "AiFloatingChat.planRateLimited";
  if (error?.status === 400 || error?.status === 413) return "AiFloatingChat.planTooLong";
  return "AiFloatingChat.planFailed";
}

/* 助手回覆失敗同理：422 是請求內容超出後端上限，跟 400／413 一樣要換一段新對話。 */
export function chatErrorKey(error) {
  if (error?.timeout || error?.status === 408) return "AiFloatingChat.chatTimedOut";
  if (error?.status === 429) return "AiFloatingChat.chatRateLimited";
  if ([400, 413, 422].includes(error?.status)) return "AiFloatingChat.chatTooLong";
  return "AiFloatingChat.genericErrorFallback";
}

/* ── 教學環境編輯頁的分頁網址 ─────────────────────────────────────── */

export function isEnvironmentEditorPath(path = "") {
  return /^\/course-template-management\/[^/?]+(?:\?|$)/.test(path);
}

/**
 * 「建立教學環境」流程的步驟只換編輯頁的分頁：已經在某個環境的編輯頁（或先前去過）就留在
 * 那個環境，否則開新的；從建立班級過去時帶上回到原班級的網址。
 */
export function environmentStepPath(currentPath, resumePath, tab) {
  const base = isEnvironmentEditorPath(currentPath) ? currentPath
    : isEnvironmentEditorPath(resumePath) ? resumePath : "/course-template-management/new";
  const [pathname, search = ""] = base.split("?");
  const params = new URLSearchParams(search);
  params.set("tab", tab === "machines" ? "machines" : "basic");
  if (!isEnvironmentEditorPath(base) || base === "/course-template-management/new") {
    const [currentPage, currentSearch = ""] = currentPath.split("?");
    const classId = new URLSearchParams(currentSearch).get("classId");
    if (currentPage === "/class-setup" && classId) {
      const back = new URLSearchParams({ classId, step: "3" });
      params.set("returnTo", `/class-setup?${back}`);
    }
  }
  return `${pathname}?${params}`;
}
