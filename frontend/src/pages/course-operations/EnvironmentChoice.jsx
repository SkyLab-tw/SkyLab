import { useTranslation } from "react-i18next";
import MIcon from "../../components/MIcon";
import styles from "./CourseOperations.module.scss";
import { environmentSpecs } from "./nodeSpecs";

/** 課程環境的一個選項。班級頁與一鍵建立精靈共用，避免兩邊各長一套。
 *  disabled：送出中不讓人再改選，避免選到一半的環境被送出去。 */
export default function EnvironmentChoice({ candidate, selected, suggested, onSelect, disabled = false }) {
  const { t } = useTranslation("teaching");
  const specs = environmentSpecs(candidate.nodes);
  return <button
    type="button"
    className={`${selected ? styles.envChoiceSelected : ""}${suggested ? ` ${styles.envChoiceSuggested}` : ""}`}
    aria-pressed={selected}
    disabled={disabled}
    onClick={onSelect}
  >
    <span className={styles.envChoiceIcon}><MIcon name="account_tree" size={20} /></span>
    <div>
      <strong><span>{candidate.name}</span><i>v{candidate.version}</i></strong>
      <p>{candidate.description || t("ClassWorkspacePage.noDescriptionFallback")}</p>
    </div>
    {/* 規格是挑環境時真正要比的：一行 12px 文字，「每人幾台」帶圖示、深一點當重點 */}
    <div className={styles.envChoiceSpecs}>
      <span className={styles.envChoiceUnit}><MIcon name="dns" size={14} />{t("ClassWorkspacePage.perStudentUnit", { count: candidate.nodes.length })}</span>
      <span>{specs.cpu} CPU</span>
      <span>{specs.memory} GB RAM</span>
      <span>{specs.disk} GB</span>
    </div>
    {/* 整列就是按鈕：沒選的列不放「選擇」，靠滑過的淡底表示可以點；選中的列標主色「✓ 已選擇」 */}
    {selected ? <em><MIcon name="check" size={16} />{t("ClassWorkspacePage.selectedLabel")}</em> : null}
  </button>;
}
