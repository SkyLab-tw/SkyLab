/* title/suggestions 是模組層級常數，無法呼叫 hook，改存 key，實際 render 處再 t() */
const PAGE_CONTEXTS = [
  { match: /^\/dashboard/, titleKey: "AiFloatingChat.pageDashboardTitle", suggestionKeys: ["AiFloatingChat.pageDashboardSuggestion1", "AiFloatingChat.pageDashboardSuggestion2", "AiFloatingChat.pageDashboardSuggestion3"] },
  { match: /^\/my-resources/, titleKey: "AiFloatingChat.pageMyResourcesTitle", suggestionKeys: ["AiFloatingChat.pageMyResourcesSuggestion1", "AiFloatingChat.pageMyResourcesSuggestion2", "AiFloatingChat.pageMyResourcesSuggestion3"] },
  { match: /^\/my-requests/, titleKey: "AiFloatingChat.pageMyRequestsTitle", suggestionKeys: ["AiFloatingChat.pageMyRequestsSuggestion1", "AiFloatingChat.pageMyRequestsSuggestion2", "AiFloatingChat.pageMyRequestsSuggestion3"] },
  { match: /^\/resource-mgmt/, titleKey: "AiFloatingChat.pageResourceMgmtTitle", suggestionKeys: ["AiFloatingChat.pageResourceMgmtSuggestion1", "AiFloatingChat.pageResourceMgmtSuggestion2", "AiFloatingChat.pageResourceMgmtSuggestion3"] },
  { match: /^\/request-review/, titleKey: "AiFloatingChat.pageRequestReviewTitle", suggestionKeys: ["AiFloatingChat.pageRequestReviewSuggestion1", "AiFloatingChat.pageRequestReviewSuggestion2", "AiFloatingChat.pageRequestReviewSuggestion3"] },
  { match: /^\/ip-management/, titleKey: "AiFloatingChat.pageIpManagementTitle", suggestionKeys: ["AiFloatingChat.pageIpManagementSuggestion1", "AiFloatingChat.pageIpManagementSuggestion2", "AiFloatingChat.pageIpManagementSuggestion3"] },
  { match: /^\/firewall/, titleKey: "AiFloatingChat.pageFirewallTitle", suggestionKeys: ["AiFloatingChat.pageFirewallSuggestion1", "AiFloatingChat.pageFirewallSuggestion2", "AiFloatingChat.pageFirewallSuggestion3"] },
  { match: /^\/domain/, titleKey: "AiFloatingChat.pageDomainTitle", suggestionKeys: ["AiFloatingChat.pageDomainSuggestion1", "AiFloatingChat.pageDomainSuggestion2", "AiFloatingChat.pageDomainSuggestion3"] },
  { match: /^\/gateway/, titleKey: "AiFloatingChat.pageGatewayTitle", suggestionKeys: ["AiFloatingChat.pageGatewaySuggestion1", "AiFloatingChat.pageGatewaySuggestion2", "AiFloatingChat.pageGatewaySuggestion3"] },
  { match: /^\/ai-api-review/, titleKey: "AiFloatingChat.pageAiApiReviewTitle", suggestionKeys: ["AiFloatingChat.pageAiApiReviewSuggestion1", "AiFloatingChat.pageAiApiReviewSuggestion2", "AiFloatingChat.pageAiApiReviewSuggestion3"] },
  { match: /^\/ai-api-keys/, titleKey: "AiFloatingChat.pageAiApiKeysTitle", suggestionKeys: ["AiFloatingChat.pageAiApiKeysSuggestion1", "AiFloatingChat.pageAiApiKeysSuggestion2", "AiFloatingChat.pageAiApiKeysSuggestion3"] },
  { match: /^\/ai-monitoring/, titleKey: "AiFloatingChat.pageAiMonitoringTitle", suggestionKeys: ["AiFloatingChat.pageAiMonitoringSuggestion1", "AiFloatingChat.pageAiMonitoringSuggestion2", "AiFloatingChat.pageAiMonitoringSuggestion3"] },
  { match: /^\/ai-api/, titleKey: "AiFloatingChat.pageAiApiTitle", suggestionKeys: ["AiFloatingChat.pageAiApiSuggestion1", "AiFloatingChat.pageAiApiSuggestion2", "AiFloatingChat.pageAiApiSuggestion3"] },
  { match: /^\/templates/, titleKey: "AiFloatingChat.pageTemplatesTitle", suggestionKeys: ["AiFloatingChat.pageTemplatesSuggestion1", "AiFloatingChat.pageTemplatesSuggestion2", "AiFloatingChat.pageTemplatesSuggestion3"] },
  { match: /^\/gpu-mgmt/, titleKey: "AiFloatingChat.pageGpuMgmtTitle", suggestionKeys: ["AiFloatingChat.pageGpuMgmtSuggestion1", "AiFloatingChat.pageGpuMgmtSuggestion2", "AiFloatingChat.pageGpuMgmtSuggestion3"] },
  { match: /^\/monitoring/, titleKey: "AiFloatingChat.pageMonitoringTitle", suggestionKeys: ["AiFloatingChat.pageMonitoringSuggestion1", "AiFloatingChat.pageMonitoringSuggestion2", "AiFloatingChat.pageMonitoringSuggestion3"] },
];

const DEFAULT_CONTEXT = {
  titleKey: "AiFloatingChat.pageDefaultTitle",
  suggestionKeys: ["AiFloatingChat.pageDefaultSuggestion1", "AiFloatingChat.pageDefaultSuggestion2", "AiFloatingChat.pageDefaultSuggestion3"],
};

/** 目前路徑的頁名與建議問題；沒有專屬設定的頁面用通用的那一組。 */
export function pageContextFor(pathname) {
  return PAGE_CONTEXTS.find((item) => item.match.test(pathname)) ?? DEFAULT_CONTEXT;
}
