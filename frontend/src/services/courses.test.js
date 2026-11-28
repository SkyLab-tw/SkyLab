/**
 * courses.test.js
 * 驗證 CoursesService 的 URL、method 與 body。
 */

import { beforeEach, describe, expect, test, vi } from "vitest";
import { CoursesService } from "./courses";

function fakeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
}

const jsonRes = (status, body = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const blobRes = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  blob: async () => body,
});

let fetchMock;

beforeEach(() => {
  vi.stubGlobal("localStorage", fakeStorage());
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

describe("CoursesService", () => {
  test("首頁課表與提醒使用各自的學生 API", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonRes(200, []))
      .mockResolvedValueOnce(jsonRes(200, []));

    await CoursesService.listSchedule();
    await CoursesService.listReminders();

    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/courses/schedule");
    expect(fetchMock.mock.calls[1][0]).toContain("/api/v1/courses/reminders");
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
    expect(fetchMock.mock.calls[1][1].method).toBe("GET");
  });

  test("listClasses 以 GET 打 /courses/classes", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(200, []));
    await CoursesService.listClasses();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/courses\/classes$/);
    expect(init.method).toBe("GET");
  });

  test("getClass 與 getAiAssignments 用班級 id 打各自的端點", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonRes(200, { id: "class-1", title: "Linux" }))
      .mockResolvedValueOnce(jsonRes(200, []));

    await CoursesService.getClass("class-1");
    await CoursesService.getAiAssignments("class-1");

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/courses\/classes\/class-1$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/api\/v1\/courses\/classes\/class-1\/ai-assignments$/);
    expect(fetchMock.mock.calls[1][1].method).toBe("GET");
  });

  test("學生以整週任務切換自己的完成狀態", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(200, { completed: true }));

    await CoursesService.updateAssignmentCompletion("class-1", "assignment-1", true);

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/v1/courses/classes/class-1/ai-assignments/assignment-1/completion",
    );
    expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      completed: true,
    });
  });

  test("學生取得已發布的每週任務並透過受保護端點預覽 PDF", async () => {
    const pdf = new Blob(["weekly-pdf"], { type: "application/pdf" });
    fetchMock
      .mockResolvedValueOnce(jsonRes(200, [{ id: "week-1", title: "Linux 權限" }]))
      .mockResolvedValueOnce(blobRes(200, pdf));

    await CoursesService.getWeeklyTasks("class-1");
    const result = await CoursesService.getWeeklyTaskDocument("class-1", "week-1", "file-1");

    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/courses/classes/class-1/weekly-tasks");
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
    expect(fetchMock.mock.calls[1][0]).toContain(
      "/api/v1/courses/classes/class-1/weekly-tasks/week-1/files/file-1",
    );
    expect(fetchMock.mock.calls[1][1].method).toBe("GET");
    expect(result).toBe(pdf);
  });

  test("getPracticeMachines 取得課程的所有班級機器", async () => {
    fetchMock.mockResolvedValueOnce(jsonRes(200, []));

    await CoursesService.getPracticeMachines("class-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/courses/classes/class-1/practice-machines");
    expect(init.method).toBe("GET");
  });

  test("AI 任務的 PDF 走作業身分驗證端點", async () => {
    const pdf = new Blob(["task-pdf"], { type: "application/pdf" });
    fetchMock.mockResolvedValueOnce(blobRes(200, pdf));

    const result = await CoursesService.getAiAssignmentSourceDocument("class-1", "assignment-1");

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/v1/courses/classes/class-1/ai-assignments/assignment-1/source-document",
    );
    expect(result).toBe(pdf);
  });

});
