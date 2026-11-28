import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";
import MIcon from "../MIcon";
import OctoPet from "../OctoPet/OctoPet";
import OctoAvatar from "../OctoPet/OctoAvatar";
import { getRouteGuide } from "../UserGuide/routeGuides";
import { describePlan } from "./planText";
import styles from "./AiFloatingChat.module.scss";

// markdown 解析器很大，等真的有 AI 回覆要顯示時才載入
const MarkdownContent = lazy(() => import("./MarkdownContent"));

const pathOnly = (path) => String(path ?? "").split(/[?#]/)[0];

/* 流程卡：步驟由伺服器的流程定義組出來，這裡只負責排版。
   不標「做到哪一步」——換到某一頁不代表那一步做完了，助手也沒有別的依據；
   只標出哪些步驟就在目前這一頁（aria-current），其餘靠由上而下的順序表達。 */
function FlowCard({ flow, currentPath, busy, onStep }) {
  return (
    <div className={styles.flowCard}>
      <strong className={styles.flowTitle}>{flow.title}</strong>
      <ol className={styles.stepList}>
        {flow.steps.map((step, position) => {
          const index = step.index ?? position;
          const recommend = step.action === "recommend";
          return (
            <li key={index}>
              {/* action 步驟由助手就地完成（規劃配置），不換頁 */}
              <button
                type="button"
                disabled={recommend && busy}
                aria-current={!recommend && pathOnly(step.path) === currentPath ? "location" : undefined}
                onClick={() => onStep(flow, { ...step, index })}
              >
                {recommend
                  ? <MIcon name="tune" size={17} />
                  : <span className={styles.stepIndex} aria-hidden="true">{position + 1}</span>}
                <span>
                  <strong>{step.title}</strong>
                  {step.detail && <small>{step.detail}</small>}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* 規劃出來的配置＋一鍵帶去填好的申請單（申請表單沒開著時才給這張卡） */
function PlanCard({ prefill, onOpenPage }) {
  const { t } = useTranslation("components");
  const lines = describePlan(prefill, t);
  return (
    <div className={styles.planCard}>
      {lines.length > 0 && (
        <ul className={styles.planSpec}>
          {lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      <button type="button" onClick={() => onOpenPage({ path: "/my-requests", state: { create: true, prefill } })}>
        <MIcon name="edit_note" size={17} />
        <span>
          <strong>{t("AiFloatingChat.planGoToFormTitle")}</strong>
          <small>{t("AiFloatingChat.planGoToFormDetail")}</small>
        </span>
      </button>
    </div>
  );
}

/* 快速回覆晶片：點一下就等於打了那句話。配置問卷進行中多一顆「直接產生配置」與進度。 */
function ChoiceRow({ choices, asking, busy, onSend }) {
  const { t } = useTranslation("components");
  return (
    <div className={styles.choiceBlock}>
      {asking && (
        <span className={styles.choiceProgress}>
          {t("AiFloatingChat.answeredProgress", { answered: asking.answered ?? 0, total: asking.total ?? 0 })}
        </span>
      )}
      <div className={styles.choiceRow}>
        {choices.map((choice) => (
          <button key={choice} type="button" disabled={busy} onClick={() => onSend(choice)}>
            {choice}
          </button>
        ))}
        {asking && (
          <button
            type="button"
            className={styles.choiceSkip}
            disabled={busy}
            onClick={() => onSend(t("AiFloatingChat.choiceSkipButton"))}
          >
            {t("AiFloatingChat.choiceSkipButton")}
          </button>
        )}
      </div>
    </div>
  );
}

/* 頁面按鈕：伺服器依權限組好的目的地。有專屬聚光燈導覽的頁面旁邊多一顆「帶我看」：
   換過去之後直接開始那一頁的導覽。 */
function PageList({ pages, onOpenPage }) {
  const { t } = useTranslation("components");
  return (
    <div className={styles.actionList}>
      {pages.map((page) => (
        <div key={`${page.path}:${JSON.stringify(page.state ?? null)}`} className={styles.actionItem}>
          <button type="button" className={styles.actionMain} onClick={() => onOpenPage(page)}>
            <span>
              <strong>{page.title}</strong>
              {page.reason && <small>{page.reason}</small>}
            </span>
            <MIcon name="arrow_forward" size={17} />
          </button>
          {getRouteGuide(pathOnly(page.path)) && (
            <button
              type="button"
              className={styles.actionTour}
              onClick={() => onOpenPage(page, { tour: true })}
              aria-label={t("AiFloatingChat.tourPageAriaLabel", { title: page.title })}
            >
              <MIcon name="tour" size={16} />
              {t("AiFloatingChat.tourPageButton")}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * 一則訊息。助手的回覆除了文字，下方依序是：規劃出來的配置、流程卡、快速回覆、
 * 「在畫面上指給我看」、頁面按鈕——先給結果，再給接下來可以做的事。
 */
export default function AssistantMessage({
  message, live = false, currentPath, busy = false, onSend, onOpenPage, onFlowStep, onPointAt,
}) {
  const { t } = useTranslation("components");
  const isUser = message.role === "user";
  const asking = message.plan?.status === "ask" ? message.plan : null;
  const choices = message.choices ?? [];
  return (
    <div className={`${styles.message} ${isUser ? styles.messageUser : styles.messageAssistant}`}>
      {/* 最新一則回覆是整隻會動的章魚（安靜模式），較舊的回覆是靜態頭像 */}
      {!isUser && (
        <span className={`${styles.messageAvatar} ${live ? styles.messageAvatarLive : ""}`}>
          {live ? <OctoPet scale={2} quiet /> : <OctoAvatar />}
        </span>
      )}
      <div className={styles.messageContent}>
        {/* 模型不可用時伺服器回的是固定說明：講明白，使用者才不會以為 AI 就只會答這樣 */}
        {message.degraded && (
          <small className={styles.degradedNote}>
            <MIcon name="info" size={14} />
            {t("AiFloatingChat.degradedNotice")}
          </small>
        )}
        {/* 模型回的是 markdown（清單、粗體、程式碼），直接印出來會看到一堆星號 */}
        {isUser ? (
          <div className={styles.messageText}>{message.content}</div>
        ) : (
          <div className={`${styles.messageText} ${styles.markdown}`}>
            <Suspense fallback={message.content}>
              <MarkdownContent>{message.content}</MarkdownContent>
            </Suspense>
          </div>
        )}
        {message.plan?.prefill && <PlanCard prefill={message.plan.prefill} onOpenPage={onOpenPage} />}
        {message.flow?.steps?.length > 0 && (
          <FlowCard flow={message.flow} currentPath={currentPath} busy={busy} onStep={onFlowStep} />
        )}
        {(choices.length > 0 || asking) && (
          <ChoiceRow choices={choices} asking={asking} busy={busy} onSend={onSend} />
        )}
        {message.spotlight && (
          <button type="button" className={styles.pointBtn} onClick={() => onPointAt(message)}>
            <MIcon name="ads_click" size={16} />
            {t("AiFloatingChat.pointAtButton")}
          </button>
        )}
        {message.pages?.length > 0 && <PageList pages={message.pages} onOpenPage={onOpenPage} />}
      </div>
    </div>
  );
}
