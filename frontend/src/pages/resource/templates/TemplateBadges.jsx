import { useTranslation } from "react-i18next";
import styles from "./TemplatesPage.module.scss";

function useTemplateStatusLabel() {
  const { t } = useTranslation("resource");
  return {
    creating: t("TemplateBadges.statusCreating"),
    ready: t("TemplateBadges.statusReady"),
    updating: t("TemplateBadges.statusUpdating"),
    failed: t("TemplateBadges.statusFailed"),
    deleted: t("TemplateBadges.statusDeleted"),
  };
}

const TEMPLATE_STATUS_CLASS = {
  creating: "badge_info",
  ready: "badge_success",
  updating: "badge_info",
  failed: "badge_danger",
  deleted: "badge_muted",
};

export function TemplateStatusBadge({ status }) {
  const templateStatusLabel = useTemplateStatusLabel();
  const label = templateStatusLabel[status] ?? status;
  /* title：範本表格欄寬固定，較長的英文狀態會在欄內截斷 */
  return (
    <span className={`${styles.badge} ${styles[TEMPLATE_STATUS_CLASS[status] ?? "badge_muted"]}`} title={label}>
      {label}
    </span>
  );
}

