import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../contexts/AuthContext";
import { AccountService } from "../../services/account";
import { useOctoMood } from "./octoMood";
import PageShell from "./PageShell";
import styles from "./LoginPage.module.scss";

/* 驗證狀態 → 章魚心情 */
const STATUS_MOOD = { checking: "thinking", success: "done", error: "error" };

function VerifyEmailChangeBody() {
  const { t } = useTranslation("personal");
  const { user } = useAuth();
  const { setMood } = useOctoMood();
  const [status, setStatus] = useState("checking");

  useEffect(() => {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("token");
    url.searchParams.delete("token");
    window.history.replaceState(window.history.state, "", url);
    if (!token) {
      setStatus("error");
      return;
    }
    AccountService.confirmEmailChange(token)
      .then(() => setStatus("success"))
      .catch(() => setStatus("error"));
  }, []);

  useEffect(() => {
    setMood(STATUS_MOOD[status]);
  }, [status, setMood]);

  return (
    <>
      <h1 className={styles.title}>{t("ProfileTab.emailVerifyTitle")}</h1>
      <p className={styles.lead} role="status">
        {status === "checking"
          ? t("ProfileTab.emailVerifying")
          : status === "success"
            ? t("ProfileTab.emailVerified")
            : t("ProfileTab.emailVerifyFailed")}
      </p>
      <p className={styles.footerText}>
        <a className={styles.link} href={user ? "/account" : "/login"}>{t("ProfileTab.emailVerifyContinue")}</a>
      </p>
    </>
  );
}

/** 換信箱驗證信的連結（/verify-email-change?token=…） */
export default function VerifyEmailChangePage() {
  return (
    <PageShell scene="verify">
      <VerifyEmailChangeBody />
    </PageShell>
  );
}
