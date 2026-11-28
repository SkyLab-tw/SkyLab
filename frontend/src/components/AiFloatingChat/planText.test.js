import { describe, expect, test } from "vitest";
import { describePlan, stripThinkTags } from "./planText";

describe("describePlan", () => {
  test("把配置講成人看得懂的幾行", () => {
    expect(describePlan({
      resource_type: "vm",
      cores: 8,
      memory_mb: 16384,
      disk_gb: 100,
      gpu_mapping_id: "gpu-a",
      mode: "immediate",
    })).toEqual([
      "類型：虛擬機",
      "規格：8 核心 · 16.0 GB RAM · 100 GB 硬碟",
      "GPU：gpu-a",
      "時段：立即使用",
    ]);
  });

  test("沒有的欄位就不要生出一行「-」", () => {
    expect(describePlan({ resource_type: "lxc" })).toEqual(["類型：LXC 容器"]);
    expect(describePlan()).toEqual([]);
  });

  test("帶入 t 時用介面語言，插值照樣帶進去", () => {
    const t = (key, vars) => `${key}${vars ? JSON.stringify(vars) : ""}`;
    expect(describePlan({ resource_type: "lxc", cores: 2 }, t)).toEqual([
      'AiFloatingChat.planTypeLine{"type":"AiFloatingChat.resourceTypeLxc"}',
      'AiFloatingChat.planSpecLine{"spec":"AiFloatingChat.planCores{\\"cores\\":2}"}',
    ]);
  });
});

describe("stripThinkTags", () => {
  test("拿掉沒收乾淨的思考區塊，空值回空字串", () => {
    expect(stripThinkTags("<think>先想一下</think>\n已準備配置")).toBe("已準備配置");
    expect(stripThinkTags("  直接是答案  ")).toBe("直接是答案");
    expect(stripThinkTags(null)).toBe("");
  });
});
