import { useTranslation } from "react-i18next";
import PasswordInput from "../../../components/PasswordInput/PasswordInput";
import { useShyHandlers } from "../octoMood";
import styles from "../LoginPage.module.scss";

/** 密碼欄：聚焦時章魚舉書不偷看；children 放欄位下方的補充（例如密碼規則） */
export default function PasswordField({ id, label, value, onChange, disabled, placeholder, children }) {
  const { t } = useTranslation("login");
  const shy = useShyHandlers();
  return (
    <div className={styles.field} {...shy}>
      <label htmlFor={id}>{label}</label>
      <PasswordInput
        id={id}
        placeholder={placeholder ?? t("LoginPage.passwordPlaceholder")}
        value={value}
        onChange={onChange}
        disabled={disabled}
        required
      />
      {children}
    </div>
  );
}
