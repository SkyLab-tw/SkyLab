import { describe, expect, it } from "vitest";
import {
  assignmentsUntilToday,
  buildPracticeMachines,
  pickCurrentCourse,
  pickCurrentWeek,
  practiceMachineActionLabel,
} from "./studentDashboard";

describe("assignmentsUntilToday", () => {
  it("保留今天以前的所有任務、排除未來任務並依日期排列", () => {
    const assignments = assignmentsUntilToday([
      { id: "today", approved_at: "2026-08-25T15:00:00+08:00" },
      { id: "future", approved_at: "2026-08-26T09:00:00+08:00" },
      { id: "older", approved_at: "2026-08-18T09:00:00+08:00" },
      { id: "legacy", approved_at: null },
    ], new Date("2026-08-25T10:00:00+08:00"));

    expect(assignments.map((item) => item.id)).toEqual(["legacy", "older", "today"]);
  });
});

describe("buildPracticeMachines", () => {
  it("保留課程中的多台機器角色，並合併即時資源狀態", () => {
    const machines = buildPracticeMachines([
      { machine_node_id: "main", name: "操作主機", role: "主要練習機", resource_type: "qemu", vmid: 218, status: "completed" },
      { machine_node_id: "db", name: "資料庫主機", role: "資料庫驗證", resource_type: "lxc", vmid: null, status: "pending" },
    ], [
      { vmid: 218, name: "student-main", type: "qemu", status: "running" },
    ]);

    expect(machines).toHaveLength(2);
    expect(machines[0]).toMatchObject({
      classMachineName: "操作主機",
      classMachineRole: "主要練習機",
      name: "student-main",
      status: "running",
    });
    expect(machines[1]).toMatchObject({
      classMachineName: "資料庫主機",
      vmid: null,
      status: "pending",
    });
  });
});

describe("practiceMachineActionLabel", () => {
  it("課堂機器只顯示自動開機狀態，不提供學生啟動操作", () => {
    expect(practiceMachineActionLabel({ vmid: 218, status: "running" })).toBe("進入機器");
    expect(practiceMachineActionLabel({ vmid: 218, status: "stopped" })).toBe("啟動並進入");
    expect(practiceMachineActionLabel({ vmid: null, status: "pending" })).toBe("環境配置中");
  });

  it("開機 task 還在跑（starting）時顯示啟動中，不當成可進入", () => {
    expect(practiceMachineActionLabel({ vmid: 438, status: "starting" })).toBe("正在啟動…");
  });
});

describe("pickCurrentCourse", () => {
  const courses = [
    { id: "ended", title: "已結束" },
    { id: "later", title: "稍後" },
    { id: "now", title: "上課中" },
    { id: "idle", title: "學期外" },
  ];

  it("優先挑正在上課的課程，不管它在清單或課表裡排第幾", () => {
    const picked = pickCurrentCourse(courses, [
      { id: "ended", state: "ended", start_at: "2026-09-29T01:00:00Z" },
      { id: "later", state: "later", start_at: "2026-09-29T06:00:00Z" },
      { id: "now", state: "now", start_at: "2026-09-29T03:00:00Z" },
    ]);

    expect(picked.id).toBe("now");
  });

  it("沒有正在上課的就依序挑今天稍後、可課後練習、今天已結束", () => {
    expect(pickCurrentCourse(courses, [
      { id: "ended", state: "ended", start_at: "2026-09-29T01:00:00Z" },
      { id: "later", state: "later", start_at: "2026-09-29T06:00:00Z" },
    ]).id).toBe("later");
    expect(pickCurrentCourse(courses, [
      { id: "ended", state: "ended", start_at: "2026-09-29T01:00:00Z" },
      { id: "idle", state: "available", start_at: "2026-10-01T01:00:00Z" },
    ]).id).toBe("idle");
  });

  it("同狀態取開始時間較早的那一門", () => {
    const picked = pickCurrentCourse(courses, [
      { id: "later", state: "later", start_at: "2026-09-29T08:00:00Z" },
      { id: "now", state: "later", start_at: "2026-09-29T06:00:00Z" },
    ]);

    expect(picked.id).toBe("now");
  });

  it("課表裡不在我的課程裡的列不算；課表對不上時取清單第一門，空清單回 null", () => {
    expect(pickCurrentCourse(courses, [{ id: "other", state: "now" }]).id).toBe("ended");
    expect(pickCurrentCourse(courses, []).id).toBe("ended");
    expect(pickCurrentCourse(courses, undefined).id).toBe("ended");
    expect(pickCurrentCourse([], [{ id: "now", state: "now" }])).toBeNull();
    expect(pickCurrentCourse(undefined, undefined)).toBeNull();
  });
});

describe("pickCurrentWeek", () => {
  const weeks = [
    { id: "w3", week_number: 3, session_date: "2026-10-13" },
    { id: "w1", week_number: 1, session_date: "2026-09-29" },
    { id: "w2", week_number: 2, session_date: "2026-10-06" },
    { id: "w4", week_number: 4, session_date: "2026-10-20" },
  ];

  it("本週是上課日期在今天以前（含今天）的最後一週", () => {
    expect(pickCurrentWeek(weeks, new Date("2026-10-16T04:00:00Z"))?.id).toBe("w3");
    expect(pickCurrentWeek(weeks, new Date("2026-10-13T01:00:00Z"))?.id).toBe("w3");
  });

  it("學期還沒開始取第一週；沒有週次是 null", () => {
    expect(pickCurrentWeek(weeks, new Date("2026-09-01T04:00:00Z"))?.id).toBe("w1");
    expect(pickCurrentWeek([], new Date())).toBeNull();
  });
});
