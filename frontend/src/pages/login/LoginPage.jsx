import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../contexts/AuthContext";
import { AccountService } from "../../services/account";
import { getLoginMethods } from "../../services/auth";
import PageShell from "./PageShell";
import DeviceApprovalView from "./views/DeviceApprovalView";
import ForgotView from "./views/ForgotView";
import LoginView from "./views/LoginView";
import RegisterView from "./views/RegisterView";
import ResetView from "./views/ResetView";
import TotpStepView from "./views/TotpStepView";

function readParam(name) {
  return new URLSearchParams(window.location.search).get(name) ?? "";
}

function clearParam(name) {
  const url = new URL(window.location.href);
  url.searchParams.delete(name);
  window.history.replaceState(null, "", url.toString());
}

/**
 * 登入頁：登入、兩步驟驗證、忘記密碼、註冊、重設密碼（?token=）與桌面 App 的裝置授權（?device_code=）。
 * 這裡只管「現在是哪個畫面」和裝置授權流程；各畫面在 views/，外框與章魚在 PageShell。
 *
 * @param {{ view?: string, methods?: object, user?: object }} [preview] 開發預覽頁（/dev/login）用：
 *   直接開某個畫面、假裝後端開了哪些登入方式、假裝已登入的帳號；正式路由不傳
 */
export default function LoginPage({ preview } = {}) {
  const { t } = useTranslation("login");
  const { user } = useAuth();
  const [resetToken, setResetToken] = useState(() => readParam("token"));
  const [deviceCode, setDeviceCode] = useState(() => readParam("device_code"));
  const [deviceApproval, setDeviceApproval] = useState({ status: "idle", error: "" });
  const approvalKeyRef = useRef("");
  const [chosenView, setView] = useState(() => preview?.view ?? (readParam("token") ? "reset" : "login"));
  // 帶著 device_code 且已登入：一律是裝置授權同意頁（還沒登入就先照常登入）
  const view = deviceCode && user ? "device" : chosenView; // "login" | "totp" | "forgot" | "register" | "reset" | "device"
  const [totpToken, setTotpToken] = useState("");
  // 後端啟用的登入方式（決定是否顯示「校園帳號」分頁）與機器人驗證 site key；
  // 公開端點，取不到就只顯示 Email、不顯示驗證框（後端若已啟用會回錯誤訊息）
  const [fetchedMethods, setFetchedMethods] = useState(null);
  const loginMethods = preview?.methods ?? fetchedMethods;
  const turnstileSiteKey = loginMethods?.turnstile_site_key ?? "";

  useEffect(() => {
    let cancelled = false;
    getLoginMethods()
      .then((methods) => {
        if (!cancelled) setFetchedMethods(methods);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onPop = () => {
      const token = readParam("token");
      setDeviceCode(readParam("device_code"));
      setResetToken(token);
      setView(token ? "reset" : "login");
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // 裝置授權必須由使用者明確按下「授權此裝置」，不可在頁面載入時自動核准：
  // 否則任何人把 /login?device_code=... 丟給已登入的使用者，就能拿到對方
  // 帳號的桌面 App token（釣魚）。
  const approveDevice = async () => {
    if (!deviceCode || !user) return;

    const approvalKey = `${deviceCode}:${user.id ?? user.email ?? "current"}`;
    if (approvalKeyRef.current) return;
    approvalKeyRef.current = approvalKey;

    setDeviceApproval({ status: "approving", error: "" });
    try {
      await AccountService.approveDesktopDevice(deviceCode);
      setDeviceApproval({ status: "approved", error: "" });
    } catch (err) {
      approvalKeyRef.current = "";
      setDeviceApproval({
        status: "error",
        error: err?.message ?? t("LoginPage.deviceApprovalError"),
      });
    }
  };

  const declineDevice = async () => {
    if (!deviceCode || approvalKeyRef.current) return;
    approvalKeyRef.current = `decline:${deviceCode}`;
    setDeviceApproval({ status: "declining", error: "" });
    try {
      await AccountService.declineDesktopDevice(deviceCode);
    } catch (err) {
      approvalKeyRef.current = "";
      setDeviceApproval({
        status: "error",
        error: err?.message ?? t("LoginPage.deviceApprovalError"),
      });
      return;
    }
    clearParam("device_code");
    setDeviceCode("");
    setDeviceApproval({ status: "idle", error: "" });
    // 已登入使用者回到首頁（整頁重載讓 App 重新判斷路由）
    window.location.replace("/");
  };

  const goLogin = () => setView("login");

  const startTotp = useCallback((challenge) => {
    setTotpToken(challenge.totpToken);
    setView("totp");
  }, []);

  const finishReset = () => {
    clearParam("token");
    setResetToken("");
    goLogin();
  };

  return (
    <PageShell>
      {view === "login" && (
        <LoginView
          deviceApproval={Boolean(deviceCode)}
          ldapEnabled={Boolean(loginMethods?.ldap)}
          signupEnabled={Boolean(loginMethods?.signup_enabled)}
          turnstileSiteKey={turnstileSiteKey}
          onTotp={startTotp}
          onForgot={() => setView("forgot")}
          onRegister={() => setView("register")}
        />
      )}
      {view === "totp" && <TotpStepView totpToken={totpToken} onBack={goLogin} />}
      {view === "forgot" && <ForgotView onBack={goLogin} />}
      {view === "register" && loginMethods?.signup_enabled && (
        <RegisterView turnstileSiteKey={turnstileSiteKey} onBack={goLogin} />
      )}
      {view === "reset" && <ResetView token={resetToken} onDone={finishReset} />}
      {view === "device" && (
        <DeviceApprovalView
          status={deviceApproval.status}
          error={deviceApproval.error}
          user={user ?? preview?.user}
          onApprove={approveDevice}
          onDecline={declineDevice}
        />
      )}
    </PageShell>
  );
}
