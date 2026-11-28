/**
 * eventStream.js
 * 讀 Server-Sent Events 回應。瀏覽器的 EventSource 只能 GET、也帶不了 Authorization，
 * 所以用 fetch 的回應串流自己讀；認證與錯誤格式由 api.js 的 apiPostEventStream 處理。
 */
import { requestTimeoutError } from "./fetchWithTimeout";

/** 伺服器閒著時每 15 秒送一次 keep-alive；超過這段時間完全沒資料就當成斷線 */
export const EVENT_STREAM_IDLE_TIMEOUT_MS = 45_000;

const invalidStream = () => ({ status: 502, message: "Invalid event stream" });

/**
 * 一則事件的文字 → { event, data }。只有註解（keep-alive）的區塊回 null。
 * data 一律是 JSON；多行 data 依規格以換行相接。
 */
export function parseEventBlock(block) {
  let event = "message";
  const data = [];
  for (const line of block.split(/\r\n|\r|\n/)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const raw = colon === -1 ? "" : line.slice(colon + 1);
    const value = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    throw invalidStream();
  }
}

/**
 * 把回應讀到結束，每收到一則事件就呼叫 onEvent({ event, data })。
 *
 * @param {Response} response
 * @param {{ onEvent: (event: {event: string, data: any}) => void,
 *   idleTimeoutMs?: number, beforeEvent?: () => void }} options
 *   beforeEvent 在交出每一則事件之前呼叫，丟例外就停止讀取（登出、換帳號之後不再處理舊回應）。
 */
export async function readEventStream(
  response,
  { onEvent, idleTimeoutMs = EVENT_STREAM_IDLE_TIMEOUT_MS, beforeEvent } = {},
) {
  if (!response.body) throw invalidStream();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let timedOut = false;
  let timer = null;
  const armTimer = () => {
    clearTimeout(timer);
    timer = idleTimeoutMs > 0
      ? setTimeout(() => {
          timedOut = true;
          reader.cancel().catch(() => {});
        }, idleTimeoutMs)
      : null;
  };
  const deliver = (block) => {
    const parsed = parseEventBlock(block);
    if (!parsed) return;
    beforeEvent?.();
    onEvent?.(parsed);
  };

  try {
    while (true) {
      armTimer();
      const { value, done } = await reader.read();
      if (timedOut) throw requestTimeoutError();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      let boundary = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      while (boundary) {
        deliver(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary[0].length);
        boundary = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      }
      if (done) break;
    }
    // 最後一則後面沒有空行就斷了：不完整，不交出去
  } finally {
    clearTimeout(timer);
    await reader.cancel().catch(() => {});
  }
}
