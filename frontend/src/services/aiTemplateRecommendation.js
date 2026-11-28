import { apiPost } from "./api";

const BASE = "/api/v1/ai/template-recommendation";

/* 預設 15 秒遠不夠：規劃最多等模型 60 秒（逾時改用規則配置）再加一次檢查。
   前端先放棄的話，後端算好的結果就白算了。 */
export const AI_RECOMMEND_TIMEOUT_MS = 120_000;

export const AiTemplateRecommendationApi = {
  /** 依對話與問到的需求（intake_facts）規劃一份可以直接填進申請單的配置。 */
  recommend(requestBody) {
    return apiPost(`${BASE}/recommend`, requestBody, { timeoutMs: AI_RECOMMEND_TIMEOUT_MS });
  },
};
