import MIcon from "../../../components/MIcon";
import styles from "../LoginPage.module.scss";

/** 卡片左上的返回鈕（回登入、登出…） */
export default function BackButton({ icon = "arrow_back", onClick, disabled = false, children }) {
  return (
    <button type="button" className={styles.backBtn} onClick={onClick} disabled={disabled}>
      <MIcon name={icon} size={18} />
      {children}
    </button>
  );
}
