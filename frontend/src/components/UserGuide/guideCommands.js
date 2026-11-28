/**
 * 聚光燈導覽的對外命令：AI 助手用它在畫面上「指給使用者看」。
 *
 * UserGuide 掛載時把自己註冊進來；沒掛（登入頁、單獨渲染助手的測試）時，所有命令都安靜地不做事。
 * 用模組層級的註冊表而不是 window 事件，是因為其中一支要有回傳值（目前頁面指得到哪些步驟）。
 *
 * 命令的形狀：
 *   { type: "tour" }                             目前頁面的完整導覽
 *   { type: "spot", stepId }                     只對目前頁面導覽的某一步打光
 *   { type: "spot", selector, title, text }      對任意錨點打光，標題與說明由呼叫端提供
 */

let api = null;
let arrival = null;

/* 換頁命令的有效期：頁面是 lazy 載入的，但超過這個時間還沒到就當作使用者去了別的地方 */
const ARRIVAL_TTL_MS = 15_000;

/** 只留路徑：去掉查詢字串、錨點與結尾的斜線，兩邊才比得起來。 */
export function guidePathOf(path) {
  return String(path ?? "").split(/[?#]/)[0].replace(/\/+$/, "") || "/";
}

/** UserGuide 掛載時呼叫；回傳解除註冊的函式。 */
export function registerGuideApi(next) {
  api = next;
  return () => {
    if (api === next) api = null;
  };
}

/** 目前頁面的導覽步驟裡，現在在畫面上指得到的那些：[{ id, title }]。 */
export function listGuideSteps() {
  return api?.listSteps() ?? [];
}

/** 立刻執行一個命令；沒有 UserGuide 或命令無效時回 false。 */
export function executeGuideCommand(command) {
  if (!api || !command) return false;
  if (command.type === "tour") {
    api.tour();
    return true;
  }
  if (command.type === "spot") {
    return command.selector
      ? api.spotSelector({ selector: command.selector, title: command.title, text: command.text })
      : api.spotStep(String(command.stepId));
  }
  return false;
}

/** 換頁之後才要做的命令：到了那一頁由 UserGuide 取走執行。後下的命令蓋掉前一個。 */
export function requestGuideOnArrival(path, command) {
  arrival = { path: guidePathOf(path), command, at: Date.now() };
}

/** 這個路徑有沒有等著執行的命令。只看不取，真的執行了再由 UserGuide 清掉。 */
export function peekArrivalCommand(pathname) {
  if (!arrival) return null;
  if (Date.now() - arrival.at > ARRIVAL_TTL_MS) {
    arrival = null;
    return null;
  }
  return arrival.path === guidePathOf(pathname) ? arrival.command : null;
}

export function clearArrivalCommand(command) {
  if (!command || arrival?.command === command) arrival = null;
}

/**
 * 「到某一頁做某個命令」：已經在那一頁就立刻做，否則記下來等換頁。
 * 回傳是否已經立刻執行，呼叫端據此決定還要不要換頁。
 */
export function runGuideCommandAt(targetPath, currentPath, command) {
  if (guidePathOf(targetPath) === guidePathOf(currentPath)) return executeGuideCommand(command);
  requestGuideOnArrival(targetPath, command);
  return false;
}
