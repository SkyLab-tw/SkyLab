import { useState } from "react";
import { useTranslation } from "react-i18next";
import Modal from "../../../components/Modal/Modal";
import { useConfirm } from "../../../components/ConfirmDialog/ConfirmProvider";
import styles from "./AdminPage.module.scss";

/* 順序同原本頁面上的註冊設定：信箱註冊、審核、Google 自動建帳 */
const SWITCHES = [
  { key: "signup_enabled", label: "AdminPage.signupEnabled", hint: "AdminPage.signupEnabledHint" },
  { key: "approval_required", label: "AdminPage.approvalRequired", hint: "AdminPage.approvalRequiredHint" },
  { key: "google_signup_enabled", label: "AdminPage.googleSignupEnabled", hint: "AdminPage.googleSignupEnabledHint" },
];

function toDraft(policy) {
  return {
    signup_enabled: Boolean(policy?.signup_enabled),
    approval_required: Boolean(policy?.approval_required),
    google_signup_enabled: Boolean(policy?.google_signup_enabled),
    student_email_domain: policy?.student_email_domain ?? "",
  };
}

function sameDraft(a, b) {
  return SWITCHES.every(({ key }) => a[key] === b[key])
    && a.student_email_domain.trim() === b.student_email_domain.trim();
}

/**
 * 註冊設定對話框：三個註冊開關與學號信箱網域一起改，按「儲存」才送出（只存一次、只跳一則提示）。
 * 草稿在開啟時取一次，背景刷新不會蓋掉正在改的值；有改動時按取消、×、Esc 或點遮罩，先確認要不要捨棄。
 *
 * @param {object} policy 目前的註冊政策（開啟時的快照當草稿起點）
 * @param {boolean} saving 送出中：欄位與按鈕鎖住，Esc、點遮罩、× 都不關
 * @param {(payload: object) => Promise<unknown>} onSave 送出要更新的欄位；成功後由父層關閉對話框
 */
export default function RegistrationSettingsDialog({ policy, saving = false, closing = false, onClose, onSave }) {
  const { t } = useTranslation("system");
  const confirm = useConfirm();
  const [initial] = useState(() => toDraft(policy));
  const [draft, setDraft] = useState(initial);
  const dirty = !sameDraft(draft, initial);

  function setField(key, value) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  async function requestClose() {
    if (saving) return;
    if (dirty) {
      const ok = await confirm({
        title: t("UnsavedGuard.title", { ns: "common" }),
        message: t("AdminPage.registrationDiscardMessage"),
        confirmText: t("AdminPage.registrationDiscard"),
        danger: true,
      });
      if (!ok) return;
    }
    onClose();
  }

  function submit(event) {
    event.preventDefault();
    if (!dirty || saving) return;
    onSave({ ...draft, student_email_domain: draft.student_email_domain.trim() || null });
  }

  return (
    <Modal
      as="form"
      onSubmit={submit}
      closing={closing}
      onClose={requestClose}
      busy={saving}
      closeButton
      size="md"
      title={t("AdminPage.registrationSettingsTitle")}
      actions={
        <>
          <button type="button" className={styles.btnSecondary} onClick={requestClose} disabled={saving}>
            {t("AdminPage.cancel")}
          </button>
          <button type="submit" className={styles.btnPrimary} disabled={!dirty || saving}>
            {saving ? t("AdminPage.saving") : t("AdminPage.save")}
          </button>
        </>
      }
    >
      <div className={styles.settingList}>
        {SWITCHES.map(({ key, label, hint }) => (
          <label key={key} className={styles.settingOption}>
            <input
              type="checkbox"
              checked={draft[key]}
              disabled={saving}
              onChange={(event) => setField(key, event.target.checked)}
            />
            <span>
              <strong>{t(label)}</strong>
              <small>{t(hint)}</small>
            </span>
          </label>
        ))}
      </div>

      <label className={styles.field}>
        <span>{t("AdminPage.studentEmailDomain")}</span>
        <input
          id="admin-student-email-domain"
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="school.edu.tw"
          value={draft.student_email_domain}
          disabled={saving}
          onChange={(event) => setField("student_email_domain", event.target.value)}
        />
        <em className={styles.fieldHint}>{t("AdminPage.studentEmailDomainHint")}</em>
      </label>
    </Modal>
  );
}
