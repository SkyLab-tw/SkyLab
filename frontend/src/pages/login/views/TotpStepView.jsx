import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../../contexts/AuthContext";
import { useOctoScene, useOctoSubmit } from "../octoMood";
import BackButton from "./BackButton";
import styles from "../LoginPage.module.scss";

/* 挑戰 token 逾時：不算出錯，直接回登入表單重新輸入帳密 */
const EXPIRED = Symbol("totp-expired");

/** 兩步驟驗證：第一階段（密碼／Google／校園帳號）通過後輸入 Authenticator 驗證碼 */
export default function TotpStepView({ totpToken, onBack }) {
  const { t } = useTranslation("login");
  const { totpLogin } = useAuth();
  const { loading, error, setError, run } = useOctoSubmit();
  useOctoScene("totp");
  const [code, setCode] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const digits = code.replace(/\D/g, "");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (digits.length !== 6) {
      setError(t("LoginPage.totpCodeLength"));
      return;
    }
    const { ok, result } = await run(async () => {
      try {
        return await totpLogin(totpToken, digits);
      } catch (err) {
        if (err?.status === 401) return EXPIRED;
        throw err;
      }
    }, t("LoginPage.totpErrorDefault"));
    if (result === EXPIRED) {
      onBack();
    } else if (!ok) {
      setCode("");
      inputRef.current?.focus();
    }
  };

  return (
    <>
      <BackButton onClick={onBack} disabled={loading}>
        {t("LoginPage.backToLogin")}
      </BackButton>
      <h1 className={styles.title}>{t("LoginPage.totpTitle")}</h1>

      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.field}>
          <label htmlFor="totp-code">{t("LoginPage.totpCodeLabel")}</label>
          <input
            ref={inputRef}
            id="totp-code"
            className={styles.codeInput}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]*"
            maxLength={7}
            placeholder="000000"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ""))}
            disabled={loading}
            required
          />
        </div>

        {error && <p className={styles.error}>{error}</p>}

        <button type="submit" className={styles.btn} disabled={loading || digits.length !== 6}>
          {loading ? t("LoginPage.totpVerifying") : t("LoginPage.totpVerify")}
        </button>
      </form>
      <p className={styles.hint}>{t("LoginPage.totpHelp")}</p>
    </>
  );
}
