import { useTranslation } from "react-i18next";
import { createColumnHelper, useTable } from "@tanstack/react-table";
import styles from "./MonitoringPage.module.scss";
import MIcon from "../../../components/MIcon";
import LoadingState from "../../../components/LoadingState/LoadingState";
import DataTable, { DataTableCells } from "../../../components/DataTable/DataTable";
import { baseFeatures } from "../../../components/DataTable/features";
import { useTableFitContext } from "../../../components/DataTable/TableFitContext";
import useTableFit from "../../../hooks/useTableFit";
import { useSystemHealthQuery } from "../../../queries/monitoring";
import { useLoadError } from "../../../hooks/useQueryLoadState";
import { formatDateTime } from "../../../utils/formatDate";
import usePersistedToggle from "./usePersistedToggle";

/* 任務明細收合偏好記在本機（與節點用量卡共用 usePersistedToggle） */
const OPEN_STORAGE_KEY = "skylab.monitoringHealthOpen";

/* 狀態 → 徽章色。橘色只留給「待審核」語意，異常一律紅色（見前端 style guide） */
const STATUS_BADGE = {
  ok: "badge_success",
  down: "badge_danger",
  degraded: "badge_danger",
  failing: "badge_danger",
  stale: "badge_danger",
  warning: "badge_danger",
  attention: "badge_danger",
  disabled: "badge_muted",
  unknown: "badge_muted",
  pending: "badge_muted",
};

const COMPONENT_ICONS = {
  database: "storage",
  redis: "memory",
  worker: "engineering",
  gateway: "router",
  ai_gateway: "smart_toy",
};

/* 這些元件的名稱帶有部署資訊（PVE 連線名稱、Gateway 位址、AI 模型名稱），直接用後端給的 label */
function usesBackendLabel(name) {
  return name.includes(":") || name === "gateway";
}

function componentIcon(name) {
  if (name.startsWith("pve")) return "dns";
  if (name.startsWith("ai_model:")) return "model_training";
  return COMPONENT_ICONS[name] ?? "hub";
}

function StatusBadge({ status, t }) {
  return (
    <span className={`${styles.badge} ${styles[STATUS_BADGE[status] ?? "badge_muted"]}`}>
      {t(`SystemHealth.status.${status}`, { defaultValue: status })}
    </span>
  );
}

/** unix 秒 → 「3 分鐘前」；滑過顯示完整時間 */
function Ago({ ts, now, t }) {
  if (!ts) return <span className={styles.mutedText}>—</span>;
  const diff = Math.max(0, Math.round(now - ts));
  let text;
  if (diff < 60) text = t("SystemHealth.agoSeconds", { count: diff });
  else if (diff < 3600) text = t("SystemHealth.agoMinutes", { count: Math.floor(diff / 60) });
  else if (diff < 86400) text = t("SystemHealth.agoHours", { count: Math.floor(diff / 3600) });
  else text = t("SystemHealth.agoDays", { count: Math.floor(diff / 86400) });
  return <span title={formatDateTime(ts * 1000)}>{text}</span>;
}

/* 任務排序：有問題的排前面，其餘照迴圈／名稱 */
const TASK_ORDER = { failing: 0, stale: 1, warning: 2, pending: 3, ok: 4 };

const EMPTY = Object.freeze([]);

/** 表頭文字（header 是元件，可以直接用 hook）；key 是完整的翻譯鍵 */
function ColTitle({ i18nKey }) {
  const { t } = useTranslation("system");
  return t(i18nKey);
}

/* ── 任務明細表窄版收欄（useTableFit） ──
   表格區不夠寬時依序收起耗時、連續失敗、上次執行、上次成功、最近錯誤；任務、狀態永遠在，
   收起的內容都是任務的狀態，改寫在狀態徽章底下。兩個時間排在一起：只收上次執行時接在上次成功底下，
   兩個都收時依欄位順序排在狀態底下。欄寬沿用原本的 colgroup（任務 240、狀態與時間 110、數字 90），
   狀態加寬到 130、連續失敗 100，收進來的「上次成功 3 分鐘前」一行才放得下；最近錯誤原本吃剩餘寬度，
   現在給 190（fixed layout 下表格比欄寬合計寬時，多的寬度依比例分給各欄）。
   全部欄 970px：1440（約 1003px）不用收，1366 筆電（約 929px）收掉耗時（880px），
   1100 寬視窗（約 678px）收到上次執行（670px），1440 開著 AI 助手（約 567px）收到上次成功（560px），
   手機（448px）連最近錯誤都收（370px），一律不用橫捲 */
const TASK_FIT_COLUMNS = Object.freeze([
  { id: "task", width: 240 },
  { id: "status", width: 130 },
  { id: "last_run_at", width: 110, fold: 3 },
  { id: "last_success_at", width: 110, fold: 4 },
  { id: "consecutive_failures", width: 100, fold: 2 },
  { id: "last_duration_ms", width: 90, fold: 1 },
  { id: "last_error", width: 190, fold: 5 },
]);

/* 收起的欄在狀態底下的一行小字；欄名一律寫（光看「3 分鐘前」「120 ms」看不出是什麼） */
function FoldedLine({ label, title, className, children }) {
  return (
    <div className={`${styles.foldedLine} ${className ?? ""}`} title={title}>
      <span className={styles.foldedLabel}>{label}</span>
      {children}
    </div>
  );
}

function durationText(ms) {
  return ms != null ? `${Math.round(ms)} ms` : "—";
}

function TaskNameCell({ task }) {
  const { t } = useTranslation("system");
  return (
    <>
      <span className={styles.healthTaskName} title={task.task}>{task.task}</span>
      <span className={styles.healthTaskLoop}>
        {t(`SystemHealth.loop.${task.loop}`, { defaultValue: task.loop })}
      </span>
    </>
  );
}

/* 窄版收欄時狀態欄多畫（依欄位順序）：上次執行、上次成功、連續失敗（0 次不寫）、耗時、最近錯誤（紅字一行，全文在 title） */
function TaskStatusCell({ task, now }) {
  const { t } = useTranslation("system");
  const fit = useTableFitContext();
  return (
    <>
      <StatusBadge status={task.status} t={t} />
      {fit.isFolded("last_run_at") && fit.isFolded("last_success_at") && (
        <FoldedLine label={t("SystemHealth.colLastRun")}><Ago ts={task.last_run_at} now={now} t={t} /></FoldedLine>
      )}
      {fit.isFolded("last_success_at") && (
        <FoldedLine label={t("SystemHealth.colLastSuccess")}><Ago ts={task.last_success_at} now={now} t={t} /></FoldedLine>
      )}
      {fit.isFolded("consecutive_failures") && task.consecutive_failures > 0 && (
        <FoldedLine label={t("SystemHealth.colFailures")}>{task.consecutive_failures}</FoldedLine>
      )}
      {fit.isFolded("last_duration_ms") && task.last_duration_ms != null && (
        <FoldedLine label={t("SystemHealth.colDuration")}>{durationText(task.last_duration_ms)}</FoldedLine>
      )}
      {fit.isFolded("last_error") && task.last_error && (
        <FoldedLine
          label={t("SystemHealth.colLastError")}
          title={task.last_error}
          className={`${styles.foldedLineTruncate} ${styles.foldedDanger}`}
        >
          {task.last_error}
        </FoldedLine>
      )}
    </>
  );
}

function TaskAgoCell({ ts, now }) {
  const { t } = useTranslation("system");
  return <Ago ts={ts} now={now} t={t} />;
}

/* 只收起上次執行時，它接在上次成功底下 */
function TaskLastSuccessCell({ task, now }) {
  const { t } = useTranslation("system");
  const fit = useTableFitContext();
  return (
    <>
      <Ago ts={task.last_success_at} now={now} t={t} />
      {fit.isFolded("last_run_at") && (
        <FoldedLine label={t("SystemHealth.colLastRun")}><Ago ts={task.last_run_at} now={now} t={t} /></FoldedLine>
      )}
    </>
  );
}

const columnHelper = createColumnHelper();

/* 欄位定義放模組層級：FlexRender 把函式型的 header／cell 當元件掛載，render 裡新建會整格重新掛載。
   「多久以前」的基準時間 now 跟著每次健康資料變，經 rowState 傳進儲存格 */
const taskColumns = columnHelper.columns([
  columnHelper.accessor("task", {
    header: () => <ColTitle i18nKey="SystemHealth.colTask" />,
    cell: ({ row }) => <TaskNameCell task={row.original} />,
    meta: { thClassName: styles.th, tdClassName: styles.td },
  }),
  columnHelper.accessor("status", {
    header: () => <ColTitle i18nKey="MonitoringPage.colStatus" />,
    cell: ({ row, rowState }) => <TaskStatusCell task={row.original} now={rowState.now} />,
    meta: { thClassName: styles.th, tdClassName: styles.td },
  }),
  columnHelper.accessor("last_run_at", {
    header: () => <ColTitle i18nKey="SystemHealth.colLastRun" />,
    cell: ({ row, rowState }) => <TaskAgoCell ts={row.original.last_run_at} now={rowState.now} />,
    meta: { thClassName: styles.th, tdClassName: styles.td },
  }),
  columnHelper.accessor("last_success_at", {
    header: () => <ColTitle i18nKey="SystemHealth.colLastSuccess" />,
    cell: ({ row, rowState }) => <TaskLastSuccessCell task={row.original} now={rowState.now} />,
    meta: { thClassName: styles.th, tdClassName: styles.td },
  }),
  columnHelper.accessor("consecutive_failures", {
    header: () => <ColTitle i18nKey="SystemHealth.colFailures" />,
    cell: ({ row }) => row.original.consecutive_failures,
    meta: { thClassName: styles.th, tdClassName: `${styles.td} ${styles.numericCell}` },
  }),
  columnHelper.accessor("last_duration_ms", {
    header: () => <ColTitle i18nKey="SystemHealth.colDuration" />,
    cell: ({ row }) => durationText(row.original.last_duration_ms),
    meta: { thClassName: styles.th, tdClassName: `${styles.td} ${styles.numericCell}` },
  }),
  columnHelper.accessor("last_error", {
    header: () => <ColTitle i18nKey="SystemHealth.colLastError" />,
    cell: ({ row }) => (row.original.last_error ? (
      <span className={styles.healthError} title={row.original.last_error}>
        {row.original.last_error}
      </span>
    ) : (
      <span className={styles.mutedText}>—</span>
    )),
    meta: { thClassName: styles.th, tdClassName: styles.td },
  }),
]);

export default function SystemHealthCard() {
  const { t } = useTranslation("system");
  const [open, toggleOpen] = usePersistedToggle(OPEN_STORAGE_KEY);
  /* 30 秒背景刷新、分頁隱藏時不輪詢；背景失敗時沿用上一筆，只有還沒拿到資料才顯示錯誤 */
  const healthQuery = useSystemHealthQuery();
  const health = healthQuery.data ?? null;
  /* 還沒拿到資料時的失敗看 useLoadError（沒資料時 v5 每次重抓都把 status 改回 pending、清掉 error，看 isError 會在背景重試時閃回載入中） */
  const error = Boolean(useLoadError(healthQuery).error);

  /* useTable 是 hook，要在下面「還沒拿到資料」的提早 return 之前呼叫，排序也跟著提前 */
  const tasks = health === null ? EMPTY : [...health.tasks].sort(
    (a, b) =>
      (TASK_ORDER[a.status] ?? 9) - (TASK_ORDER[b.status] ?? 9) ||
      a.loop.localeCompare(b.loop) ||
      a.task.localeCompare(b.task),
  );
  const table = useTable({
    features: baseFeatures,
    columns: taskColumns,
    data: tasks,
    getRowId: (task) => `${task.loop}/${task.task}`,
  });
  /* 同 useTable，要在下面的提早 return 之前呼叫 */
  const fit = useTableFit(TASK_FIT_COLUMNS);

  if (health === null) {
    return (
      <div className={styles.card} data-guide="monitoring-health">
        {error ? (
          <div className={styles.cardEmpty}>
            <MIcon name="warning" size={24} />
            <p>{t("SystemHealth.errorFetch")}</p>
          </div>
        ) : (
          <LoadingState text={t("SystemHealth.loading")} />
        )}
      </div>
    );
  }

  const now = new Date(health.generated_at).getTime() / 1000;
  const problemTasks = health.tasks.filter((task) =>
    ["failing", "stale", "warning"].includes(task.status),
  );

  return (
    <div className={styles.card} data-guide="monitoring-health">
      <button
        type="button"
        className={styles.cardHeaderToggle}
        onClick={toggleOpen}
        aria-expanded={open}
      >
        <h2 className={styles.cardTitle}>
          <MIcon name="monitor_heart" size={18} />
          {t("SystemHealth.title")}
          <StatusBadge status={health.status} t={t} />
        </h2>
        <span className={styles.cardHeaderMeta}>
          {problemTasks.length > 0
            ? t("SystemHealth.problemTasks", { count: problemTasks.length })
            : t("SystemHealth.tasksAllOk", { count: health.tasks.length })}
          <MIcon name={open ? "expand_less" : "expand_more"} size={18} />
        </span>
      </button>

      {/* 依賴元件：永遠顯示，一眼看出 DB／Redis／worker／PVE／Gateway 誰掛了 */}
      <div className={styles.healthComponents}>
        {health.components.map((component) => (
          <div key={component.name} className={styles.healthComponent}>
            <MIcon name={componentIcon(component.name)} size={18} />
            <div className={styles.healthComponentText}>
              {/* pve:<id>／gateway 直接用後端給的名稱；「:」在 i18next 是命名空間分隔符。
                  名稱太長會被截斷（例如 LLM 模型名），滑過顯示全名 */}
              {(() => {
                const name = usesBackendLabel(component.name)
                  ? component.label
                  : t(`SystemHealth.component.${component.name}`, { defaultValue: component.label });
                return <span className={styles.healthComponentName} title={name}>{name}</span>;
              })()}
              <span className={styles.healthComponentMeta} title={component.detail ?? ""}>
                {component.status === "ok" && component.latency_ms != null
                  ? `${component.latency_ms} ms`
                  : (component.detail ?? "")}
              </span>
            </div>
            <StatusBadge status={component.status} t={t} />
          </div>
        ))}
      </div>

      {open && (
        <>
          {health.heartbeat_source === "memory" && (
            <p className={styles.healthNotice}>
              <MIcon name="info" size={16} />
              {t("SystemHealth.memorySourceNotice")}
            </p>
          )}

          {health.loops.length > 0 && (
            <div className={styles.healthLoops}>
              {health.loops.map((loop) => (
                <div key={loop.loop} className={styles.healthLoop}>
                  <span className={styles.healthLoopName}>
                    {t(`SystemHealth.loop.${loop.loop}`, { defaultValue: loop.loop })}
                  </span>
                  <StatusBadge status={loop.status} t={t} />
                  <span className={styles.mutedText}>
                    {t("SystemHealth.lastTick")}{" "}
                    <Ago ts={loop.leader_last_tick_at} now={now} t={t} />
                  </span>
                </div>
              ))}
            </div>
          )}

          <div ref={fit.ref} className={styles.tableScroll}>
            <DataTable
              table={table}
              className={styles.table}
              fit={fit}
              renderRow={(row) => (
                <tr key={row.id} className={styles.tr}>
                  <DataTableCells row={row} rowState={{ now }} />
                </tr>
              )}
            />
          </div>
        </>
      )}
    </div>
  );
}
