import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../contexts/AuthContext";
import MIcon from "../MIcon";
import OctoPet from "../OctoPet/OctoPet";
import PageHelpHint from "./PageHelpHint";
import AssistantMessage from "./AssistantMessage";
import useAssistantChat from "./useAssistantChat";
import { pageContextFor } from "./pageContexts";
import { streamStatusKey } from "./taskState";
import { getRouteGuide, USER_GUIDE_START_EVENT } from "../UserGuide/routeGuides";
import useAutoGrowTextarea from "../../hooks/useAutoGrowTextarea";
import useDialogPresence from "../../hooks/useDialogPresence";
import useBodyScrollLock from "../../hooks/useBodyScrollLock";
import { useUnsavedChanges } from "../../contexts/UnsavedChangesContext";
import styles from "./AiFloatingChat.module.scss";

const allowLeave = async () => true;

/** 取得跳離確認；沒有掛 UnsavedChangesProvider（單獨渲染助手的測試）時一律放行。
 *  useUnsavedChanges 內部固定先呼叫 useContext 才丟錯，hook 順序不受 try 影響。 */
function useConfirmLeave() {
  try {
    return useUnsavedChanges().confirmLeave;
  } catch {
    return allowLeave;
  }
}

/* 助手只有一個對話框、一條路：每句話都交給後端的模型判斷要回答、帶路、指給你看還是規劃機器。
   開場把做得到的事列出來，使用者才會用到後面幾個。 */
const CAPABILITIES = [
  "AiFloatingChat.capabilityAnswerTitle",
  "AiFloatingChat.capabilityFindTitle",
  "AiFloatingChat.capabilityPointTitle",
  "AiFloatingChat.capabilityRecommendTitle",
];

function displayName(user, t) {
  return user?.full_name?.trim() || user?.email?.split("@")[0] || t("AiFloatingChat.defaultUserName");
}

/* 回覆中：章魚學士敲筆電，飄出 0 和 1（原本是三個跳動的點）。
   助手用過工具、還要再想一輪時，旁邊多一行字說明它做到哪了（statusKey）。 */
function TypingIndicator({ statusKey = null }) {
  const { t } = useTranslation("components");
  return (
    <div className={styles.typing} role="status" aria-label={t("AiFloatingChat.aiReplyingAriaLabel")}>
      <OctoPet activity="thinking" scale={3} />
      {statusKey && <span className={styles.typingStatus}>{t(statusKey)}</span>}
    </div>
  );
}

/* 低於這個寬度時面板是覆蓋層（蓋住頁面），導覽換頁後要順手收起來 */
const OVERLAY_QUERY = "(max-width: 1439px)";

/* 回覆對齊到訊息區上緣時留的距離：剛好避開上緣的淡出帶（.messages 的 mask） */
const REPLY_TOP_GAP_PX = 16;

/* 面板左側剩下的寬度低於這個值（手機全螢幕抽屜、窄視窗）就不讓位：
   對話框擠不進去，寧可讓面板蓋著 */
const MIN_DIALOG_AREA_PX = 480;

/**
 * forceOverlay：頁面自己有對話欄時（版面 context 的 setAssistantOverlay），寬螢幕也用覆蓋層開啟，不並排。
 */
export default function AiFloatingChat({ open = false, onOpenChange = () => {}, forceOverlay = false }) {
  // 關閉時先播放離場動畫再卸載面板
  const presence = useDialogPresence(open, 180);
  /* <1440px 時面板是覆蓋層（fixed + backdrop），開啟期間鎖住底下頁面捲動；
     寬螢幕的並排停靠模式不鎖。頁面要求覆蓋（forceOverlay）時寬螢幕也一樣 */
  const [narrowViewport, setNarrowViewport] = useState(
    () => window.matchMedia(OVERLAY_QUERY).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(OVERLAY_QUERY);
    const onChange = (event) => setNarrowViewport(event.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  const overlayMode = narrowViewport || forceOverlay;
  useBodyScrollLock(presence.open && overlayMode);
  /* 面板佔掉的右側寬度寫進 --ai-panel-inset，對話框遮罩（dialog-overlay-avoid-ai）
     據此改在左側剩餘空間置中。量 root 而非 panel：panel 有 translateX 進場動畫，
     root 則有寬度轉場，轉場每一格都會觸發 ResizeObserver，對話框跟著平滑讓位 */
  const rootRef = useRef(null);
  const panelOpen = presence.open && !presence.closing;
  useEffect(() => {
    const docEl = document.documentElement;
    const el = rootRef.current;
    if (!panelOpen || !el) {
      docEl.style.removeProperty("--ai-panel-inset");
      return undefined;
    }
    const update = () => {
      const left = el.getBoundingClientRect().left;
      const inset = left >= MIN_DIALOG_AREA_PX ? Math.max(0, docEl.clientWidth - left) : 0;
      docEl.style.setProperty("--ai-panel-inset", `${Math.round(inset)}px`);
    };
    update();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    ro?.observe(el);
    window.addEventListener("resize", update);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", update);
      docEl.style.removeProperty("--ai-panel-inset");
    };
  }, [panelOpen]);

  const location = useLocation();
  const confirmLeave = useConfirmLeave();
  const { user } = useAuth();
  const { t } = useTranslation("components");
  const close = () => onOpenChange(false);
  const assistant = useAssistantChat({ overlayMode, onClose: close, confirmLeave });
  const { messages, loading, streaming, failedRef, activeSurface, activeSurfaceId } = assistant;
  /* 回答邊寫邊顯示：寫出字之前是敲筆電的章魚，有字之後就是一則正在變長的回覆。
     排在對話的最後一格，寫完時由完整的回應原地接手（同一個 key，不會重播進場動畫）。 */
  const writingText = loading ? streaming?.text ?? "" : "";
  const shownMessages = writingText
    ? [...messages, { role: "assistant", content: writingText }]
    : messages;
  const [input, setInput] = useState("");

  const inputRef = useRef(null);
  /* 浮動按鈕的章魚要知道：面板關著時回覆好了（或出錯）還沒被看到，就冒對話泡泡提醒。
     面板開著就把游標還給輸入框——等回覆的期間它是停用的，要等重新啟用之後才接得住焦點 */
  const [fabNotice, setFabNotice] = useState(null);
  const wasLoadingRef = useRef(false);
  useEffect(() => {
    if (!loading && wasLoadingRef.current) {
      if (open) inputRef.current?.focus();
      else setFabNotice(failedRef.current ? "error" : "done");
    }
    wasLoadingRef.current = loading;
  }, [loading, open, failedRef]);
  useEffect(() => {
    if (open) setFabNotice(null);
  }, [open]);
  const fabActivity = loading ? "thinking" : fabNotice ?? "idle";

  /* 只有最新一則回覆旁的章魚會動；AI 正在回覆時下方已有敲筆電的章魚，這時全部回覆都用靜態頭像 */
  let liveReplyIndex = -1;
  if (!loading) {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role !== "user") { liveReplyIndex = i; break; }
    }
  }

  const scrollRef = useRef(null);

  const pageContext = pageContextFor(location.pathname);
  /* 頁名優先用畫面定義的標題：它涵蓋每一頁，pageContexts 只列了一部分，
     沒列到的會落到「SkyLab」，等於沒講。 */
  const currentPageName = activeSurface?.title ?? t(pageContext.titleKey);

  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 120);
  }, [open]);

  // 輸入框從兩行開始，隨內容長高；到上限（.composer textarea 的 max-height）就停，之後框內捲動。
  // 助手打開、輸入框出現後才量
  useAutoGrowTextarea(inputRef, input, presence.open);

  /* 自己送出的訊息與「回覆中」捲到底；助手回覆出來時，改把「剛問的那句＋回覆開頭」對齊到
     訊息區上緣——長回答（頁面說明、流程步驟）要從第一行讀起，不是停在結尾。
     回覆比訊息區矮時，瀏覽器會把捲動位置夾在最底，效果等同捲到底。
     回覆是邊寫邊長高的：寫的期間只往下補到定位點，不把已經往下讀的人拉回來；寫完時
     位置已經對好，不再動。 */
  const anchoredWhileWritingRef = useRef(false);
  useEffect(() => {
    const box = scrollRef.current;
    if (!box) return;
    const last = messages[messages.length - 1];
    const writing = Boolean(writingText);
    if (!last || (!writing && (loading || last.role === "user"))) {
      box.scrollTop = box.scrollHeight;
      anchoredWhileWritingRef.current = false;
      return;
    }
    const reply = box.lastElementChild;
    const askedMessage = writing ? last : messages[messages.length - 2];
    const asked = askedMessage?.role === "user" ? reply?.previousElementSibling : null;
    const anchor = asked ?? reply;
    // offsetTop 不受進場動畫的位移與捲動中的位置影響；兩者同一個 offsetParent（面板）
    const target = anchor ? Math.max(0, anchor.offsetTop - box.offsetTop - REPLY_TOP_GAP_PX) : box.scrollHeight;
    if (writing) {
      if (box.scrollTop < target) box.scrollTop = target;
      anchoredWhileWritingRef.current = true;
      return;
    }
    if (anchoredWhileWritingRef.current) {
      anchoredWhileWritingRef.current = false;
      return;
    }
    box.scrollTop = target;
  }, [messages, loading, writingText]);

  function clearChat() {
    assistant.clearChat();
    setInput("");
    inputRef.current?.focus();
  }

  /* 輸入框、建議問題、快速回覆晶片都走這裡：沒有分流，就是把這句話交給助手 */
  async function submit(value = input) {
    const text = String(value).trim();
    if (!text || loading) return;
    setInput("");
    await assistant.send(text);
  }

  /* 頁面導覽按鈕、建議晶片與提示泡泡：這一頁有前端導覽就關掉助手、一步步帶著看；
     沒有導覽的頁面才替使用者問「這個頁面怎麼用？」。使用者自己打字問的一律交給助手，不在前端猜意圖 */
  const pageTourId = getRouteGuide(location.pathname)?.id ?? null;
  const hasPageTour = Boolean(pageTourId);
  function startPageTour() {
    onOpenChange(false);
    window.dispatchEvent(new CustomEvent(USER_GUIDE_START_EVENT));
  }
  function showPageGuide() {
    if (hasPageTour) startPageTour();
    else submit(t("AiFloatingChat.pageGuideQuestion"));
  }
  const canShowPageGuide = hasPageTour || Boolean(activeSurfaceId);

  function handleKeyDown(event) {
    // 注音、倉頡選字時按 Enter 是確認選字，不是送出
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div
      ref={rootRef}
      className={[styles.root, presence.open ? styles.rootOpen : "", forceOverlay ? styles.rootOverlay : ""].filter(Boolean).join(" ")}
      /* 助手浮在對話框之上時，在這裡按的鍵（Esc、Enter…）只屬於助手：
         對話框的 Esc 關閉監聽掛在 window/document，不擋會把底下的對話框一起關掉 */
      onKeyDown={(e) => e.stopPropagation()}
    >
      {presence.open && (
        <button
          type="button"
          className={`${styles.backdrop} ${presence.closing ? styles.backdropOut : ""}`}
          onClick={close}
          aria-label={t("AiFloatingChat.closeAssistantAriaLabel")}
        />
      )}

      {presence.open && (
        <aside className={`${styles.panel} ${presence.closing ? styles.panelOut : ""}`} aria-label={t("AiFloatingChat.assistantName")} data-guide="request-ai-helper-panel">
          <header className={styles.header}>
            {/* 標頭只放名稱：原本的副標「SkyLab 智慧協作」只是標語，不帶資訊 */}
            <div className={styles.headerText}>
              <strong>{t("AiFloatingChat.assistantName")}</strong>
            </div>
            <button type="button" onClick={clearChat} disabled={loading} title={t("AiFloatingChat.newChatLabel")} aria-label={t("AiFloatingChat.newChatLabel")}>
              <MIcon name="refresh" size={19} />
            </button>
            <button type="button" onClick={close} title={t("AiFloatingChat.closeLabel")} aria-label={t("AiFloatingChat.closeLabel")}>
              <MIcon name="close" size={21} />
            </button>
          </header>

          <div className={styles.contextRow}>
            <div className={styles.contextBar}>
              <MIcon name="web_asset" size={16} />
              <span>{t("AiFloatingChat.contextViewingPage", { page: currentPageName })}</span>
            </div>
            {/* 隨時可以叫出這一頁的導覽 */}
            {canShowPageGuide && (
              <button type="button" className={styles.pageGuideBtn} onClick={showPageGuide} disabled={loading}>
                <MIcon name="tour" size={16} />
                {t("AiFloatingChat.pageGuideButton")}
              </button>
            )}
          </div>

          <div className={styles.messages} ref={scrollRef}>
            {messages.length === 0 ? (
              <div className={styles.emptyState}>
                <h2>{displayName(user, t)}{t("AiFloatingChat.greetingSuffix")}</h2>
                <p>{t("AiFloatingChat.emptyStatePrompt")}</p>
                {/* 能力要講出來，不然沒有人知道可以叫它指給你看、幫忙填表。
                    但它只是說明、不能點：做成一般的圓點清單，可點的只有下方建議問題
                    （原本白底細框的樣子像按鈕，常被誤點） */}
                <ul className={styles.capabilities}>
                  {CAPABILITIES.map((key) => (
                    <li key={key}>{t(key)}</li>
                  ))}
                </ul>
                {(canShowPageGuide || pageContext.suggestionKeys.length > 0) && (
                  <p className={styles.suggestionsLead}>{t("AiFloatingChat.suggestionsLead")}</p>
                )}
                <div className={styles.suggestions}>
                  {canShowPageGuide && (
                    <button type="button" onClick={showPageGuide}>
                      {t("AiFloatingChat.pageGuideQuestion")}
                    </button>
                  )}
                  {pageContext.suggestionKeys.map((key) => (
                    <button key={key} type="button" onClick={() => submit(t(key))}>
                      {t(key)}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              shownMessages.map((message, index) => (
                <AssistantMessage
                  key={`${message.role}-${index}`}
                  message={message}
                  live={index === liveReplyIndex}
                  currentPath={location.pathname}
                  busy={loading}
                  onSend={submit}
                  onOpenPage={assistant.openPage}
                  onFlowStep={assistant.openFlowStep}
                  onPointAt={assistant.pointAt}
                />
              ))
            )}
            {loading && !writingText && (
              <div className={`${styles.message} ${styles.messageAssistant}`}>
                <TypingIndicator statusKey={streamStatusKey(streaming?.tool)} />
              </div>
            )}
          </div>

          <footer className={styles.composerWrap}>
            <div className={styles.composer}>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t("AiFloatingChat.composerPlaceholder")}
                rows={2}
                disabled={loading}
              />
              <button type="button" onClick={() => submit()} disabled={loading || !input.trim()} aria-label={t("AiFloatingChat.sendMessageAriaLabel")}>
                <MIcon name="arrow_upward" size={20} />
              </button>
            </div>
            <small>{t("AiFloatingChat.aiDisclaimer")}</small>
          </footer>
        </aside>
      )}

      <PageHelpHint
        enabled={hasPageTour && !presence.open && !loading && !fabNotice}
        pageKey={pageTourId}
        userId={user?.id}
        onActivate={startPageTour}
      />

      {!presence.open && (
        /* 章魚學士本身就是按鈕：點擊只負責打開助手，章魚只回應游標移上去與摸頭 */
        <button
          type="button"
          className={styles.fab}
          onClick={() => onOpenChange(true)}
          title={t("AiFloatingChat.assistantName")}
          aria-label={t(fabNotice ? "AiFloatingChat.openAssistantUnreadAriaLabel" : "AiFloatingChat.openAssistantAriaLabel")}
          data-guide="request-ai-helper-button"
        >
          {/* 待機時偶爾往左走幾步（最多 8 格 = 24px）；整隻章魚一起移動，走到哪點到哪都會打開助手 */}
          <OctoPet activity={fabActivity} walkRange={8} className={styles.fabOcto} />
        </button>
      )}
    </div>
  );
}
