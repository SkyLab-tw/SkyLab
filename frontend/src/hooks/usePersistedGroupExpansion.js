import { useState } from "react";

/* 群組（班級環境、快速練習）的開合狀態記在本機，離開頁面、重整、篩選後再出現都維持使用者上次的選擇。
   只記「跟預設不同」的群組 id：預設展開的記收起的、預設收起的記展開的，沒記過的照預設；
   群組會結束消失，只留最近的 MAX_REMEMBERED 筆，清單不會無限長 */
const COLLAPSED_PREFIX = "skylab:collapsed-groups:";
const EXPANDED_PREFIX = "skylab:expanded-groups:";
const MAX_REMEMBERED = 200;

/** 沒記過、內容壞掉或 localStorage 不可用都當空清單 */
function loadIds(key) {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function saveId(key, groupId, present) {
  const ids = loadIds(key).filter((id) => id !== groupId);
  if (present) ids.push(groupId);
  try {
    window.localStorage.setItem(key, JSON.stringify(ids.slice(-MAX_REMEMBERED)));
  } catch {
    // localStorage 不可用時開合只在這次瀏覽有效
  }
}

/** 讀某個頁面（scope）收起的群組 id（預設展開的群組用） */
export function loadCollapsedGroups(scope) {
  return loadIds(COLLAPSED_PREFIX + scope);
}

export function saveGroupCollapsed(scope, groupId, collapsed) {
  saveId(COLLAPSED_PREFIX + scope, groupId, collapsed);
}

/**
 * 回傳 [expanded, toggle]。scope 區分頁面（各頁各記各的），groupId 是群組的穩定 id。
 * defaultExpanded=false 給平常不必看的區塊（如使用者管理的待審核註冊）：預設收起，展開過才記住。
 */
export default function usePersistedGroupExpansion(scope, groupId, { defaultExpanded = true } = {}) {
  const id = String(groupId);
  const key = (defaultExpanded ? COLLAPSED_PREFIX : EXPANDED_PREFIX) + scope;
  /* 清單裡有＝跟預設相反 */
  const [expanded, setExpanded] = useState(() => loadIds(key).includes(id) !== defaultExpanded);
  function toggle() {
    const next = !expanded;
    setExpanded(next);
    saveId(key, id, next !== defaultExpanded);
  }
  return [expanded, toggle];
}
