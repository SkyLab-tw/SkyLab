import { ResourcesService } from "../../../../services/resources";
import i18n from "../../../../i18n";
import { formatMonthDay, formatTime } from "../../../../utils/formatDate";
import { taipeiDateKey } from "../taipeiDate";

/* 學生課程頁（與首頁的開機流程）共用的純邏輯；不含任何畫面，方便單獨測試。 */

const defaultT = (key) => i18n.t(key, { ns: "personal" });

/* 課表狀態的先後：正在上課 → 今天稍後 → 可課後練習 → 今天已結束 */
const SCHEDULE_STATE_ORDER = { now: 0, later: 1, available: 2, ended: 3 };

/**
 * 網址沒有指定課程（或指定的不在我的課程裡）時，挑出「現在該看的那一門」。
 * 依課表狀態挑：正在上課的優先，其次今天稍後、可課後練習、今天已結束，同狀態取開始時間較早的；
 * 課表裡一門都對不上（例如都不在學期內）就取我的課程的第一門。
 * courses 與 schedule 的 id 都是班級 id。
 */
export function pickCurrentCourse(courses, schedule) {
  const list = courses ?? [];
  const byId = new Map(list.map((course) => [String(course.id), course]));
  const rank = (row) => SCHEDULE_STATE_ORDER[row.state] ?? Object.keys(SCHEDULE_STATE_ORDER).length;
  const scheduled = (schedule ?? [])
    .filter((row) => byId.has(String(row.id)))
    .sort((left, right) => (
      rank(left) - rank(right)
      || String(left.start_at ?? "").localeCompare(String(right.start_at ?? ""))
    ));
  return (scheduled.length ? byId.get(String(scheduled[0].id)) : list[0]) ?? null;
}

/** 本週：上課日期在今天（含，台北日曆日）以前的最後一週；學期還沒開始時取第一週。 */
export function pickCurrentWeek(weeks, now = new Date()) {
  const sorted = [...(weeks ?? [])].sort((left, right) => (
    String(left.session_date ?? "").localeCompare(String(right.session_date ?? ""))
    || (left.week_number ?? 0) - (right.week_number ?? 0)
  ));
  const todayKey = taipeiDateKey(now);
  return [...sorted].reverse().find((week) => String(week.session_date ?? "") <= todayKey)
    ?? sorted[0]
    ?? null;
}

/** 保留已發布到今天（含，台北日曆日）的任務，排除未來任務，並依發布日期由舊到新排列。 */
export function assignmentsUntilToday(assignments, now = new Date()) {
  const todayKey = taipeiDateKey(now);
  return [...(assignments ?? [])]
    .filter((assignment) => {
      if (!assignment?.approved_at) return true;
      const approvedAt = new Date(assignment.approved_at);
      return !Number.isNaN(approvedAt.getTime()) && taipeiDateKey(approvedAt) <= todayKey;
    })
    .sort((left, right) => {
      const leftTime = left.approved_at ? new Date(left.approved_at).getTime() : 0;
      const rightTime = right.approved_at ? new Date(right.approved_at).getTime() : 0;
      return leftTime - rightTime;
    });
}

/** 任務列上的發布日期；沒有日期或格式錯誤時退回「已發布」。 */
export function formatAssignmentDate(value, t = defaultT) {
  return formatMonthDay(value, t("studentDashboard.published"));
}

/** 把課表 API 的扁平欄位收進 schedule 物件；時間為 HH:MM（24 小時制），無法解析時留空。 */
export function normalizeSchedule(row) {
  return {
    ...row,
    schedule: {
      state: row.state,
      label: row.label,
      time: `${formatTime(row.start_at, "")}–${formatTime(row.end_at, "")}`,
      teacher: row.teacher,
      place: row.location,
    },
  };
}

/**
 * 合併「課程定義的機器」與「我的資源即時狀態」。
 */
export function buildPracticeMachines(classMachines, resources) {
  const machines = (classMachines ?? []).map((machine) => {
    const resource = (resources ?? []).find(
      (item) => machine.vmid != null && Number(item.vmid) === Number(machine.vmid),
    );
    return {
      ...machine,
      ...resource,
      classMachineName: machine.name,
      classMachineRole: machine.role,
      type: resource?.type ?? machine.resource_type,
      name: resource?.name ?? machine.name,
    };
  });

  return machines;
}

/** 課堂機器按鈕的文字；學生只看到狀態，不提供手動開關機。 */
export function practiceMachineActionLabel(machine, openingMachineId = null, t = defaultT) {
  if (machine?.vmid == null) return t("studentDashboard.actionConfiguring");
  if (openingMachineId === machine.vmid || machine.status === "starting") return t("studentDashboard.actionStarting");
  if (machine.status === "running") return t("studentDashboard.actionEnter");
  return t("studentDashboard.actionStartAndEnter");
}

/** 送出開機後輪詢資源狀態，直到 running 或次數用盡（約 90 秒）。
    後端在開機 task 跑完前回報 starting；GPU 直通機開機可達 40 秒以上。 */
export async function waitForPracticeMachine(vmid, attempts = 45) {
  let resource = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    resource = await ResourcesService.get(vmid);
    if (resource.status === "running") return resource;
    if (attempt < attempts - 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
  }
  return resource;
}
