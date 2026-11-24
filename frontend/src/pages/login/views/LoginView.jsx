import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import MIcon from "../../../components/MIcon";
import SegmentedControl from "../../../components/SegmentedControl/SegmentedControl";
import Turnstile from "../../../components/Turnstile/Turnstile";
import { useAuth } from "../../../contexts/AuthContext";
import { useOctoScene, useOctoSubmit } from "../octoMood";
import GoogleSignIn from "./GoogleSignIn";
import PasswordField from "./PasswordField";
import styles from "../LoginPage.module.scss";

/* 兩種登入方式共用同一張表單，只差帳號欄的文案與送出時的預設錯誤訊息 */
const MODES = {
  password: {
    usernameId: "username",
    passwordId: "password",
    label: "LoginPage.usernameLabel",
    placeholder: "LoginPage.usernamePlaceholder",
    fallbackError: "LoginPage.loginErrorDefault",
  },
  ldap: {
    usernameId: "ldap-username",
    passwordId: "ldap-password",
    label: "LoginPage.campusAccount",
    placeholder: "LoginPage.campusAccountPlaceholder",
    autoComplete: "username",
    fallbackError: "LoginPage.ldapLoginErrorDefault",
  },
};

function formatGoogleLoginError(err, t) {
  const message = err?.message ?? "";
  if (message === "Google account is not registered") {
    return t("LoginPage.googleErrorNotRegistered");
  }
  if (message === "Inactive user") {
    return t("LoginPage.googleErrorInactiveUser");
  }
  if (message === "Invalid Google token audience") {
    return t("LoginPage.googleErrorAudienceMismatch");
  }
  if (message === "Invalid Google token") {
    return t("LoginPage.googleErrorInvalidToken");
  }
  return message || t("LoginPage.googleErrorGeneric");
}

/**
 * 登入表單：Email 密碼／校園帳號（後端有開才出現切換）＋Google 登入。
 *
 * @param {(challenge: { totpToken: string }) => void} onTotp 帳號已綁定兩步驟驗證：第一階段通過後
 *   拿到挑戰 token，交給外層切到驗證碼畫面（要是穩定的參考）
 */
export default function LoginView({
  onForgot,
  onRegister,
  onTotp,
  deviceApproval = false,
  ldapEnabled = false,
  signupEnabled = false,
  turnstileSiteKey = "",
}) {
  const { t } = useTranslation("login");
  const { login, googleLogin, ldapLogin } = useAuth();
  const { loading, error, setError, fail, run } = useOctoSubmit();
  useOctoScene("login");
  const [chosenMode, setChosenMode] = useState("password");
  const mode = ldapEnabled ? chosenMode : "password";
  const copy = MODES[mode];
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // 送出中的是 Google 登入還是表單：決定哪一邊顯示「登入中」
  const [viaGoogle, setViaGoogle] = useState(false);
  // Cloudflare 機器人驗證（後端有設定金鑰才顯示）
  const [turnstileToken, setTurnstileToken] = useState("");
  const turnstileRef = useRef(null);
  const turnstilePending = Boolean(turnstileSiteKey) && !turnstileToken;

  const switchMode = (next) => {
    setChosenMode(next);
    setUsername("");
    setPassword("");
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (turnstilePending) {
      setError(t("LoginPage.turnstileRequired"));
      return;
    }
    setViaGoogle(false);
    const doLogin = mode === "ldap" ? ldapLogin : login;
    const { ok, result } = await run(
      () => doLogin(username, password, { turnstileToken }),
      t(copy.fallbackError),
    );
    // 機器人驗證的 token 只能用一次，送出失敗後換一個新的
    if (!ok) turnstileRef.current?.reset();
    else if (result?.totpRequired) onTotp(result);
  };

  const handleGoogleCredential = useCallback(
    async (credential) => {
      setViaGoogle(true);
      const { ok, result } = await run(
        () => googleLogin(credential),
        (err) => formatGoogleLoginError(err, t),
      );
      if (ok && result?.totpRequired) onTotp(result);
    },
    [googleLogin, onTotp, run, t],
  );

  const formBusy = loading && !viaGoogle;

  return (
    <>
      <h1 className={styles.title}>{t("LoginPage.login")}</h1>

      {deviceApproval && (
        <div className={styles.deviceNotice}>
          <MIcon name="devices" size={22} />
          <span>{t("LoginPage.deviceNotice")}</span>
        </div>
      )}

      {ldapEnabled && (
        <SegmentedControl
          className={styles.modeSwitch}
          ariaLabel={t("LoginPage.loginMethodsAriaLabel")}
          value={mode}
          onChange={switchMode}
          options={[
            { value: "password", label: t("LoginPage.emailTab") },
            { value: "ldap", label: t("LoginPage.campusAccount") },
          ]}
        />
      )}

      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.field}>
          <label htmlFor={copy.usernameId}>{t(copy.label)}</label>
          <input
            id={copy.usernameId}
            type="text"
            placeholder={t(copy.placeholder)}
            autoComplete={copy.autoComplete}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={loading}
            required
          />
        </div>

        <PasswordField
          id={copy.passwordId}
          label={t("LoginPage.passwordLabel")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={loading}
        />

        {mode === "password" && (
          <button type="button" className={styles.linkRight} onClick={onForgot}>
            {t("LoginPage.forgotPasswordLink")}
          </button>
        )}

        {turnstileSiteKey && (
          <Turnstile
            ref={turnstileRef}
            siteKey={turnstileSiteKey}
            action="login"
            onToken={setTurnstileToken}
          />
        )}

        {error && <p className={styles.error}>{error}</p>}

        <button type="submit" className={styles.btn} disabled={loading || turnstilePending}>
          {formBusy ? t("LoginPage.loggingIn") : t("LoginPage.login")}
        </button>
      </form>

      <GoogleSignIn busy={loading && viaGoogle} onCredential={handleGoogleCredential} onError={fail} />

      {signupEnabled && (
        <p className={styles.footerText}>
          {t("LoginPage.noAccountYet")}{" "}
          <button type="button" className={styles.link} onClick={onRegister}>
            {t("LoginPage.registerNow")}
          </button>
        </p>
      )}
    </>
  );
}
