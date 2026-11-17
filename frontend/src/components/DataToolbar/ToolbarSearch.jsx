import { useRef } from "react";
import { useTranslation } from "react-i18next";
import MIcon from "../MIcon";
import styles from "./DataToolbar.module.scss";

/**
 * 工具列上的搜尋框（36px，跟按鈕、分段切換同高）。按 Esc 清掉搜尋字。
 * placeholder 同時當無障礙名稱，寫「搜尋什麼」，例如「搜尋名稱、VMID、IP 或擁有者」。
 *
 * @param {string}   value
 * @param {Function} onChange    (value: string) => void
 * @param {string}   placeholder
 * @param {boolean}  clearable   有字時在右側放 ✕ 清除鈕（清掉後游標留在搜尋框）
 * @param {string}   className   額外樣式（例如窄螢幕撐滿一行）
 * 其餘屬性（例如導覽用的 data-guide）掛在外框 label 上
 */
export default function ToolbarSearch({ value, onChange, placeholder, clearable = false, className, ...rest }) {
  const { t } = useTranslation("common");
  const inputRef = useRef(null);
  const clear = () => {
    onChange("");
    inputRef.current?.focus();
  };
  return (
    <label {...rest} className={`${styles.search}${className ? ` ${className}` : ""}`}>
      <MIcon name="search" size={18} />
      <input
        ref={inputRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Escape" && value) onChange(""); }}
        placeholder={placeholder}
        aria-label={placeholder}
      />
      {clearable && value ? (
        <button type="button" className={styles.searchClear} onClick={clear} aria-label={t("EmptyState.clearSearch")} title={t("EmptyState.clearSearch")}>
          <MIcon name="close" size={16} />
        </button>
      ) : null}
    </label>
  );
}
