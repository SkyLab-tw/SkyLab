/**
 * 流程步驟在畫面上對應到哪個錨點：{ [flow_id]: { [步驟索引]: selector } }。
 *
 * 流程本身（步驟標題、要去哪一頁）由後端的 flows 定義，那裡刻意不記版面位置；
 * 「這一步在畫面上是哪一塊」是前端才知道的事，所以對照表放這裡。點流程步驟換頁後，
 * 助手用聚光燈把這個錨點亮出來。
 *
 * 只用頁面上本來就有的 data-guide 錨點（聚光燈導覽在用的同一批）。沒有合適錨點的
 * 步驟就不列——換了頁但不打光，比指著一個不相干的地方好。錨點不在 DOM 裡（精靈還沒
 * 走到那一步、清單是空的）時聚光燈會自己略過。flowAnchors.test.js 會檢查每個 selector
 * 都還存在於頁面原始碼。
 */
export const FLOW_ANCHORS = {
  request_machine: {
    0: '[data-guide="request-resource-settings"]',
    /* 1 是「AI 協助填寫」：助手就地規劃，不換頁 */
    2: '[data-guide="request-list"]',
    3: '[data-guide="resource-card"]',
  },
  publish_service: {
    0: '[data-guide="resource-card"]',
    1: '[data-guide="firewall-create"]',
  },
  /* 建立班級是分步精靈，一次只顯示一步：錨點只有走到那一步才在畫面上 */
  open_class: {
    0: '[data-guide="class-setup-basic"]',
    1: '[data-guide="class-setup-emails"]',
    2: '[data-guide="class-setup-env-list"]',
    3: '[data-guide="class-setup-weeks"]',
    4: '[data-guide="class-setup-provision"]',
  },
  prepare_environment: {
    0: '[data-guide="course-tpl-editor-name"]',
    1: '[data-guide="course-tpl-editor-add-bar"]',
    2: '[data-guide="course-tpl-editor-publish"]',
  },
  share_template: {
    0: '[data-guide="resource-card"]',
    1: '[data-guide="templates-create"]',
    2: '[data-guide="templates-menu"]',
  },
  review_requests: {
    0: '[data-guide="request-review-list"]',
    1: '[data-guide="jobs-table"]',
    2: '[data-guide="resource-mgmt-table"]',
  },
  review_class_batch: {
    0: '[data-guide="batch-review-list"]',
    1: '[data-guide="jobs-table"]',
    2: '[data-guide="resource-mgmt-table"]',
  },
};

/** 這個流程的這一步要亮哪個錨點；沒有登錄就回 null。 */
export function flowAnchor(flowId, stepIndex) {
  return FLOW_ANCHORS[flowId]?.[stepIndex] ?? null;
}
