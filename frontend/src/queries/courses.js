import { useQuery, useQueryClient } from "@tanstack/react-query";

import { CoursesService } from "../services/courses";
import { LIST_REFRESH_INTERVAL } from "./queryClient";

/* 學生端的課程查詢：課表、提醒、我的班級、每週任務與課堂機器。
   學生看到的「課程」就是他所在的班級，classId 一律是班級 id。 */

export const courseKeys = Object.freeze({
  all: ["courses"],
  schedule: ["courses", "schedule"],
  reminders: ["courses", "reminders"],
  classes: ["courses", "classes"],
  class: (classId) => ["courses", "class", String(classId)],
  aiAssignments: (classId) => ["courses", "aiAssignments", String(classId)],
  weeklyTasks: (classId) => ["courses", "weeklyTasks", String(classId)],
  practiceMachines: (classId) => ["courses", "practiceMachines", String(classId)],
});

/** 我的課表（學生首頁、課程頁共用） */
export function useCourseScheduleQuery({ enabled = true, refetchInterval = LIST_REFRESH_INTERVAL } = {}) {
  return useQuery({ queryKey: courseKeys.schedule, queryFn: () => CoursesService.listSchedule(), enabled, refetchInterval });
}

/** 課程提醒（JobsProvider 的提醒通知） */
export function useCourseRemindersQuery({ enabled = true, refetchInterval = LIST_REFRESH_INTERVAL, refetchOnWindowFocus } = {}) {
  return useQuery({
    queryKey: courseKeys.reminders,
    queryFn: () => CoursesService.listReminders(),
    enabled,
    refetchInterval,
    /* 只有呼叫端有指定才覆寫；明寫 undefined 會蓋掉全站預設 */
    ...(refetchOnWindowFocus === undefined ? null : { refetchOnWindowFocus }),
  });
}

/** 我加入、而且已經可以上課的班級清單 */
export function useCourseClassesQuery({ enabled = true, refetchInterval = LIST_REFRESH_INTERVAL } = {}) {
  return useQuery({ queryKey: courseKeys.classes, queryFn: () => CoursesService.listClasses(), enabled, refetchInterval });
}

export function useCourseClassQuery(classId, { enabled } = {}) {
  return useQuery({ queryKey: courseKeys.class(classId), queryFn: () => CoursesService.getClass(classId), enabled: enabled ?? (classId != null) });
}

export function useAiAssignmentsQuery(classId, { enabled } = {}) {
  return useQuery({ queryKey: courseKeys.aiAssignments(classId), queryFn: () => CoursesService.getAiAssignments(classId), enabled: enabled ?? (classId != null) });
}

export function useWeeklyTasksQuery(classId, { enabled } = {}) {
  return useQuery({ queryKey: courseKeys.weeklyTasks(classId), queryFn: () => CoursesService.getWeeklyTasks(classId), enabled: enabled ?? (classId != null) });
}

export function usePracticeMachinesQuery(classId, { enabled, refetchInterval = LIST_REFRESH_INTERVAL } = {}) {
  return useQuery({
    queryKey: courseKeys.practiceMachines(classId),
    queryFn: () => CoursesService.getPracticeMachines(classId),
    enabled: enabled ?? (classId != null),
    refetchInterval,
  });
}

export function useCourseCacheUpdater() {
  const queryClient = useQueryClient();
  return {
    invalidate() {
      return queryClient.invalidateQueries({ queryKey: courseKeys.all });
    },
    invalidateClass(classId) {
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: courseKeys.class(classId) }),
        queryClient.invalidateQueries({ queryKey: courseKeys.aiAssignments(classId) }),
        queryClient.invalidateQueries({ queryKey: courseKeys.weeklyTasks(classId) }),
      ]);
    },
  };
}
