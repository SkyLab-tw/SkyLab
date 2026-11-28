import { useContext, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../contexts/AuthContext";
import { LayoutContext } from "../../layout/layoutContext";
import { AiAssistantService, matchSurface } from "../../services/aiAssistant";
import { AiTemplateRecommendationApi } from "../../services/aiTemplateRecommendation";
import { loadAssistantChat, saveAssistantChat } from "../../utils/assistantChatStorage";
import {
  clearArrivalCommand,
  executeGuideCommand,
  guidePathOf,
  listGuideSteps,
  requestGuideOnArrival,
} from "../UserGuide/guideCommands";
import { flowAnchor } from "./flowAnchors";
import { describePlan, stripThinkTags } from "./planText";
import {
  applyStreamEvent,
  cardNote,
  chatErrorKey,
  environmentStepPath,
  historyForAssistant,
  intakeFactsPayload,
  isEnvironmentEditorPath,
  planErrorKey,
  planRequestMessages,
} from "./taskState";

const NO_MESSAGES = [];
const MAX_PAGES = 4;
/* 記住最後待過的教學環境編輯頁：流程步驟只換分頁，不該把人帶去另開一個新環境 */
const ENVIRONMENT_EDITOR = "environment-editor";

const fullPath = (location) => `${location.pathname}${location.search ?? ""}`;

/* 失敗要變成一則看得懂的訊息，而不是丟到最外層。寫成模組層級的函式，hook 本身就沒有
   try/finally（React Compiler 遇到會整支略過）。 */
async function settle(task) {
  try {
    return { ok: true, value: await task() };
  } catch (error) {
    return { ok: false, error };
  }
}

/**
 * 助手的對話狀態與送出。
 *
 * 每一句話只走一條路：連同眼前的畫面送給後端的助手，回來的是文字加上伺服器組好的卡片
 * （頁面按鈕、流程、配置問卷、要指的地方）。這裡不猜問句的類別，也不記任務進度。
 *
 * @param {{overlayMode: boolean, onClose: () => void, confirmLeave: () => Promise<boolean>}} options
 *   overlayMode：面板蓋在頁面上（窄視窗、頁面要求覆蓋）——換頁與打光之前要先收起面板。
 */
export default function useAssistantChat({ overlayMode, onClose, confirmLeave }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t, i18n } = useTranslation("components");
  /* 申請表單開著時會把自己註冊進來：規劃就地填進欄位，而且拿得到這張表單當下的真實候選。
     surface 是頁面註冊的欄位狀態，助手才知道使用者眼前填了什麼、哪裡被擋。 */
  const { requestForm, surface, requestSubmission } = useContext(LayoutContext);
  const userId = user?.id ?? null;

  /* 對話存 sessionStorage，重新整理後還原；owner 記這份對話屬於誰，換帳號時不會錯用 */
  const [chat, setChat] = useState(() => ({ owner: userId, ...loadAssistantChat(userId) }));
  const [loading, setLoading] = useState(false);
  /* 回答還在寫的時候暫時顯示的字與進度（{ text, tool }）。不放進 chat：那份每次變動都會寫
     sessionStorage，而且這些字還沒檢查過，不該被當成對話的一部分留下來。 */
  const [streaming, setStreaming] = useState(null);
  const [surfaceList, setSurfaceList] = useState([]);
  const busyRef = useRef(false);
  const failedRef = useRef(false);
  const visitedRef = useRef(new Map());
  /* 送出後要等回覆，回來時畫面可能已經換了：需要「當下」的值都從這裡拿 */
  const live = useRef({ location, requestForm, surface, activeSurfaceId: null, overlayMode, onClose, confirmLeave });

  const mine = chat.owner === userId;
  const messages = mine ? chat.messages : NO_MESSAGES;
  /* 這段對話產生過配置、而且還沒送出申請：之後申請送出時要接一句話 */
  const planned = mine && chat.planned;

  /* 目前這一頁對應到哪個畫面定義。有頁面自己註冊就用它（同一個路徑可能有多個畫面，
     例如申請列表與申請表單），否則靠路徑對照。 */
  const matched = matchSurface(surfaceList, location.pathname);
  const activeSurface = (surface?.id && surfaceList.find((item) => item.id === surface.id)) || matched;
  const activeSurfaceId = activeSurface?.id ?? surface?.id ?? null;

  useEffect(() => {
    live.current = { location, requestForm, surface, activeSurfaceId, overlayMode, onClose, confirmLeave };
  });

  /* 每個路徑最後一次待過的完整網址：流程步驟帶人回某一頁時，回到他離開時的樣子
     （例如 /class-setup?classId=42&step=3），而不是那一頁的空白起點 */
  useEffect(() => {
    const current = fullPath(location);
    visitedRef.current.set(location.pathname, current);
    if (isEnvironmentEditorPath(current)) visitedRef.current.set(ENVIRONMENT_EDITOR, current);
  }, [location]);

  useEffect(() => {
    setChat((previous) => (previous.owner === userId
      ? previous
      : { owner: userId, ...loadAssistantChat(userId) }));
  }, [userId]);

  useEffect(() => {
    if (chat.owner === userId) saveAssistantChat(userId, chat);
  }, [chat, userId]);

  /* 畫面清單只跟身分有關，載一次 */
  useEffect(() => {
    let cancelled = false;
    AiAssistantService.surfaces()
      .then((list) => { if (!cancelled) setSurfaceList(list ?? []); })
      .catch(() => { /* 對照表載不到就只剩頁面自己註冊的那一個，助手照樣能回答 */ });
    return () => { cancelled = true; };
  }, []);

  function append(message, patch = {}) {
    setChat((previous) => ({ ...previous, ...patch, messages: [...previous.messages, message] }));
  }

  /* 申請送出了：這段對話幫忙規劃過配置的話，接一句後續，並給一顆可以直接問進度的晶片。
     進度由助手去查（後端有查申請狀態的工具），前端不自己判斷。 */
  const submissionId = requestSubmission?.id ?? null;
  useEffect(() => {
    if (!submissionId || !planned) return;
    append({
      role: "assistant",
      content: t("AiFloatingChat.requestSubmitted"),
      choices: [t("AiFloatingChat.checkRequestProgress")],
    }, { planned: false });
    // 只在申請送出的那一刻觸發；planned 與 t 變動不該重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submissionId]);

  function screenSnapshot() {
    const current = live.current;
    return {
      path: fullPath(current.location),
      surfaceId: current.activeSurfaceId,
      activeTarget: current.surface?.getActiveTarget?.() ?? null,
      state: current.surface?.getState?.() ?? {},
      /* 聚光燈現在指得到的步驟：助手只能從這份清單裡挑要指哪一個 */
      guideSteps: listGuideSteps(),
    };
  }

  function replyFrom(data, sentPath) {
    const pages = (Array.isArray(data?.pages) ? data.pages : [])
      .filter((page) => page?.path && page?.title)
      .slice(0, MAX_PAGES);
    const flow = data?.flow?.steps?.length ? data.flow : null;
    const asking = data?.plan?.status === "ask"
      ? { status: "ask", answered: data.plan.answered, total: data.plan.total }
      : null;
    const choices = (Array.isArray(data?.choices) ? data.choices : []).filter(Boolean);
    const note = cardNote({ pages, flow });
    return {
      role: "assistant",
      content: String(data?.reply ?? "").trim() || t("AiFloatingChat.noReplyFallback"),
      ...(pages.length ? { pages } : {}),
      ...(flow ? { flow } : {}),
      ...(asking ? { plan: asking } : {}),
      ...(choices.length ? { choices } : {}),
      /* 要指的是送出當下那一頁的步驟，連路徑一起記：之後才按的話先回到那一頁 */
      ...(data?.spotlight?.target_id != null
        ? { spotlight: { stepId: String(data.spotlight.target_id), path: sentPath } }
        : {}),
      ...(data?.degraded ? { degraded: true } : {}),
      ...(note ? { note } : {}),
    };
  }

  /* 需求問齊了：交給規劃器產生可以直接填進申請單的配置。資源候選（作業系統、GPU、時段）
     由申請表單提供；表單沒開著時後端自己補。 */
  async function runPlan(facts, history) {
    const result = await settle(() => AiTemplateRecommendationApi.recommend({
      messages: planRequestMessages(historyForAssistant(history), facts),
      top_k: 5,
      device_nodes: [],
      form_context: live.current.requestForm?.getContext() ?? null,
      intake_facts: intakeFactsPayload(facts),
    }));
    const plan = result.ok ? result.value?.final_plan : null;
    const prefill = plan?.form_prefill;
    if (!prefill?.resource_type) {
      failedRef.current = true;
      append({
        role: "assistant",
        content: t(result.ok ? "AiFloatingChat.planFailed" : planErrorKey(result.error)),
        choices: [t("AiFloatingChat.choiceSkipButton")],
        omit: true,
      });
      return;
    }
    const summary = stripThinkTags(plan.summary);
    /* 申請表單開著就直接填進去——填好的表單本身就是結果，不需要再給一張長得像表單的卡片。
       表單沒開才帶過去，並留一張卡片，之後離開了還能再帶回來。 */
    const form = live.current.requestForm;
    if (form) form.applyPrefill(prefill);
    else navigate("/my-requests", { state: { create: true, prefill } });
    const filledNote = t("AiFloatingChat.filledFormNote");
    const content = form
      ? (summary ? `${summary}\n\n${filledNote}` : filledNote)
      : (summary || t("AiFloatingChat.recommendationIntro"));
    append({
      role: "assistant",
      content,
      ...(form ? {} : { plan: { status: "planned", prefill } }),
      note: `（已產生配置：${describePlan(prefill).join("；")}）`,
    }, { planned: true });
  }

  async function send(value) {
    const text = String(value ?? "").trim();
    if (!text || busyRef.current) return false;
    busyRef.current = true;
    failedRef.current = false;
    const asked = { role: "user", content: text };
    const history = [...messages, asked];
    append(asked);
    setLoading(true);
    const sentPath = fullPath(live.current.location);
    const result = await settle(() => AiAssistantService.chat({
      messages: historyForAssistant(history),
      locale: i18n?.language,
      screen: screenSnapshot(),
      onEvent: (event) => setStreaming((previous) => applyStreamEvent(previous, event)),
    }));
    /* 過程中顯示的字到此為止；下面附加的完整回應（或錯誤訊息）才是留在對話裡的 */
    setStreaming(null);
    if (result.ok) {
      const reply = replyFrom(result.value, sentPath);
      append(reply);
      /* 並排停靠時直接指出來；覆蓋層蓋著頁面，改由訊息上的按鈕先收面板再指。
         等回覆的期間換了頁就不指——那個步驟屬於送出當下的那一頁。 */
      if (reply.spotlight && !live.current.overlayMode && sentPath === fullPath(live.current.location)) {
        executeGuideCommand({ type: "spot", stepId: reply.spotlight.stepId });
      }
      if (result.value?.plan?.status === "ready") {
        await runPlan(result.value.plan.facts, [...history, reply]);
      }
    } else {
      failedRef.current = true;
      append({ role: "assistant", content: t(chatErrorKey(result.error)), omit: true });
    }
    busyRef.current = false;
    setLoading(false);
    return true;
  }

  function clearChat() {
    setChat({ owner: userId, messages: [], planned: false });
  }

  /* 使用者點的導覽（頁面按鈕、流程步驟、配置卡）要先確認未儲存的表單。
     覆蓋層模式先收起面板再問：面板的 backdrop 與 z-index 會蓋住確認框，也會吃掉 Esc/Enter。
     並排停靠模式的確認框會避開面板（--ai-panel-inset），可以開著問。 */
  async function goTo(path, state) {
    if (!path) return false;
    const current = live.current;
    if (current.overlayMode) current.onClose();
    if (!(await current.confirmLeave())) return false;
    navigate(path, state ? { state } : undefined);
    return true;
  }

  /* 到某一頁做某個聚光燈命令：還沒在那一頁就先記下來，到了由 UserGuide 取走；
     已經在那一頁（頂多換查詢字串）就換完直接做。沒換成（使用者不離開）就把命令收回。 */
  async function goAndGuide(target, state, command) {
    const here = live.current.location;
    const samePage = guidePathOf(target) === here.pathname;
    if (command && !samePage) requestGuideOnArrival(target, command);
    if (target === fullPath(here) && !state) {
      if (command && live.current.overlayMode) live.current.onClose();
    } else if (!(await goTo(target, state))) {
      if (command) clearArrivalCommand(command);
      return false;
    }
    if (command && samePage) executeGuideCommand(command);
    return true;
  }

  /** 頁面按鈕。tour：換過去之後開始那一頁的完整聚光燈導覽。 */
  function openPage(page, { tour = false } = {}) {
    if (!page?.path) return Promise.resolve(false);
    return goAndGuide(page.path, page.state ?? undefined, tour ? { type: "tour" } : null);
  }

  /** 流程步驟：換到那一步所在的頁面，並把那一步對應的地方亮出來。 */
  function openFlowStep(flow, step) {
    /* 這一步由助手就地完成：等於請它規劃配置 */
    if (step.action === "recommend") return send(t("AiFloatingChat.planRequestMessage"));
    const here = live.current.location;
    let target = step.path;
    let state = step.state ?? undefined;
    if (step.state?.environmentTab) {
      /* 教學環境的步驟只換編輯頁的分頁，保留正在編輯的環境與返回班級的網址 */
      target = environmentStepPath(fullPath(here), visitedRef.current.get(ENVIRONMENT_EDITOR), step.state.environmentTab);
      state = undefined;
    } else if (!state) {
      target = guidePathOf(step.path) === here.pathname
        ? fullPath(here)
        : visitedRef.current.get(step.path) ?? step.path;
    }
    const anchor = flowAnchor(flow.flow_id, step.index);
    const command = anchor ? { type: "spot", selector: anchor, title: step.title, text: step.detail } : null;
    return goAndGuide(target, state, command);
  }

  /** 「在畫面上指給我看」：回到問問題當下的那一頁，把助手挑的那一步亮出來。 */
  function pointAt(message) {
    if (!message?.spotlight) return Promise.resolve(false);
    return goAndGuide(message.spotlight.path, undefined, { type: "spot", stepId: message.spotlight.stepId });
  }

  return {
    messages,
    loading,
    streaming,
    failedRef,
    activeSurface,
    activeSurfaceId,
    send,
    clearChat,
    openPage,
    openFlowStep,
    pointAt,
  };
}
