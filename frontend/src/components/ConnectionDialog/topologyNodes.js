/**
 * 拓撲節點 → 連線對話框的機器清單。
 *
 * 老師的拓撲會帶學生的課堂機（can_manage=true），學生的拓撲會帶自己的課堂機
 * 但不能管（can_manage=false）。連線兩端都要寫規則，所以只有可管理的機器
 * 才進對話框的下拉；不是自己的機器在名稱後面帶擁有者，同一班學生的機器
 * 常常同名（web-01 × 30），沒有擁有者根本分不出來。
 */

import { KIND_META, resolveKind } from "../MachineKindBadge/machineKind";

export function canManageNode(node) {
  return node?.can_manage !== false;
}

/**
 * 拉線碰到唯讀機器時要講的原因（network 命名空間的鍵）：學生的課堂機由班級老師管；
 * 快速練習機誰都不能改（老師、管理員最常碰到的就是這種）；其他（例如失去班級的課堂機）只說沒有管理權。
 */
export function readOnlyNodeMessageKey(node) {
  if (node?.machine_kind === "quick_practice") return "FirewallPage.readOnlyNodeQuickPractice";
  if (node?.teaching_class_name) return "FirewallPage.readOnlyNode";
  return "FirewallPage.readOnlyNodeNoPermission";
}

export function nodeLabel(node) {
  if (!node) return "";
  return node.owner_name ? `${node.name} · ${node.owner_name}` : node.name;
}

/** 機器來源的翻譯鍵：與資源列表、拓撲節點的徽章同一套判斷 */
export function nodeKindLabelKey(node) {
  const kind = resolveKind({
    kind: node?.machine_kind,
    classRelation: node?.class_relation,
  });
  return KIND_META[kind].labelKey;
}

export function toDialogNodes(topologyNodes) {
  return (topologyNodes ?? [])
    .filter((n) => n.node_type !== "gateway" && n.vmid != null && canManageNode(n))
    .map((n) => ({
      key: String(n.vmid),
      vmid: n.vmid,
      name: nodeLabel(n),
      kindLabelKey: nodeKindLabelKey(n),
    }));
}
