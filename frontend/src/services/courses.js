import { apiGet, apiGetBlob, apiPut } from "./api";

/**
 * 課程服務（學生端）：正式課程總覽、每週任務、PDF 與完成狀態。
 * 學生看到的「課程」就是他所在的班級，id 一律是班級 id。
 * 欄位見後端 app/schemas/course.py。
 */
export const CoursesService = {
  /** 今天實際有排課、且學生已加入的課程。 */
  listSchedule() {
    return apiGet("/api/v1/courses/schedule");
  },

  /** 由資源期限、申請審核與近期課堂任務產生的提醒。 */
  listReminders() {
    return apiGet("/api/v1/courses/reminders");
  },

  /** 我加入、而且已經可以上課的班級清單（id 與名稱） */
  listClasses() {
    return apiGet("/api/v1/courses/classes");
  },

  /** 單一班級的 id 與名稱；不在班上或班級還沒開放時回 404 */
  getClass(classId) {
    return apiGet(`/api/v1/courses/classes/${classId}`);
  },

  /** 取得老師已核准、可讓學生查看的 AI導師檢查任務。 */
  getAiAssignments(classId) {
    return apiGet(`/api/v1/courses/classes/${classId}/ai-assignments`);
  },

  /** 取得老師在班級每週內容中正式發布的任務與 PDF。 */
  getWeeklyTasks(classId) {
    return apiGet(`/api/v1/courses/classes/${classId}/weekly-tasks`);
  },

  /** 透過有課程身分驗證的端點預覽每週任務 PDF。 */
  getWeeklyTaskDocument(classId, weekId, fileId) {
    return apiGetBlob(
      `/api/v1/courses/classes/${classId}/weekly-tasks/${weekId}/files/${fileId}`,
    );
  },

  /** 透過作業身分驗證的端點預覽老師在 AI 任務設定上傳的 PDF。 */
  getAiAssignmentSourceDocument(classId, assignmentId) {
    return apiGetBlob(
      `/api/v1/courses/classes/${classId}/ai-assignments/${assignmentId}/source-document`,
    );
  },

  /** 取得學生在此課程由班級流程分配的所有練習機器。 */
  getPracticeMachines(classId) {
    return apiGet(`/api/v1/courses/classes/${classId}/practice-machines`);
  },

  /** 學生以每週／整份任務為單位回報完成；AI導師檢查由老師統一啟動。 */
  updateAssignmentCompletion(classId, assignmentId, completed) {
    return apiPut(
      `/api/v1/courses/classes/${classId}/ai-assignments/${assignmentId}/completion`,
      { completed },
    );
  },

};
