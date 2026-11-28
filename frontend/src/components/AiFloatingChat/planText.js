import { formatDate } from "../../utils/formatDate";

/**
 * 把規劃出來的 form_prefill 講成人看得懂的幾行。
 * t 由呼叫端（畫面 render 時）帶入才會翻譯；省略 t 時維持繁中字面——寫進對話歷史給模型看的
 * 那一份用這個，不跟著介面語言變。
 */
export function describePlan(prefill = {}, t) {
  const tr = (key, options, fallback) => (t ? t(key, options) : fallback);
  const lines = [];
  if (prefill.resource_type) {
    const typeLabel = prefill.resource_type === "vm"
      ? tr("AiFloatingChat.resourceTypeVm", null, "虛擬機")
      : tr("AiFloatingChat.resourceTypeLxc", null, "LXC 容器");
    lines.push(tr("AiFloatingChat.planTypeLine", { type: typeLabel }, `類型：${typeLabel}`));
  }
  const spec = [
    prefill.cores ? tr("AiFloatingChat.planCores", { cores: prefill.cores }, `${prefill.cores} 核心`) : "",
    prefill.memory_mb
      ? tr("AiFloatingChat.planMemory", { gb: (prefill.memory_mb / 1024).toFixed(1) }, `${(prefill.memory_mb / 1024).toFixed(1)} GB RAM`)
      : "",
    prefill.disk_gb ? tr("AiFloatingChat.planDisk", { gb: prefill.disk_gb }, `${prefill.disk_gb} GB 硬碟`) : "",
  ].filter(Boolean);
  if (spec.length) lines.push(tr("AiFloatingChat.planSpecLine", { spec: spec.join(" · ") }, `規格：${spec.join(" · ")}`));
  if (prefill.gpu_mapping_id) {
    lines.push(tr("AiFloatingChat.planGpuLine", { gpu: prefill.gpu_mapping_id }, `GPU：${prefill.gpu_mapping_id}`));
  }
  if (prefill.start_at && prefill.end_at) {
    const day = (value) => formatDate(value);
    lines.push(tr(
      "AiFloatingChat.planTimeRangeLine",
      { start: day(prefill.start_at), end: day(prefill.end_at) },
      `時段：${day(prefill.start_at)} ～ ${day(prefill.end_at)}`,
    ));
  } else if (prefill.mode === "immediate") {
    lines.push(tr("AiFloatingChat.planTimeImmediate", null, "時段：立即使用"));
  }
  return lines;
}

/** 規劃器的摘要偶爾帶著沒收乾淨的思考區塊，顯示前拿掉。 */
export function stripThinkTags(text) {
  return String(text || "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
}
