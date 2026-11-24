import { useEffect, useRef } from "react";
import { useAuth } from "../../../contexts/AuthContext";
import PixelLoginPage from "./PixelLoginPage";
import styles from "./PixelLoginPreview.module.scss";

/* 預覽頁可以直接開的畫面：?view=… ；?ldap=1、?signup=1 假裝後端開了校園帳號、註冊 */
const VIEWS = [
  ["login", "登入"],
  ["forgot", "忘記密碼"],
  ["register", "註冊"],
  ["reset", "重設密碼"],
  ["totp", "兩步驟驗證"],
  ["device", "裝置授權"],
];

function readPreview() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view") ?? "login";
  const methods =
    params.has("ldap") || params.has("signup")
      ? { ldap: params.get("ldap") === "1", signup_enabled: params.get("signup") === "1" }
      : undefined;
  return {
    view: ["forgot", "register", "reset"].includes(view) ? view : "login",
    totp: view === "totp",
    device: view === "device",
    // 註冊畫面要後端開放註冊才會出現，預覽時直接假裝開了
    methods: view === "register" ? { ...methods, signup_enabled: true } : methods,
    user: view === "device" ? { email: "student@campus.edu.tw" } : undefined,
    clean: params.get("clean") === "1",
    current: view,
  };
}

/**
 * 像素風登入頁的開發預覽（/dev/login-pixel，只在 dev 模式註冊）：
 * 放在所有登入閘門之前，登入中或後端沒開也看得到；左下角切換各畫面（?clean=1 隱藏，截圖用）。
 * 在這裡真的登入成功就轉去首頁，跟正式登入頁一樣。
 */
export default function PixelLoginPreview() {
  const { user } = useAuth();
  const preview = readPreview();
  const hadUser = useRef(Boolean(user));

  useEffect(() => {
    if (user && !hadUser.current) window.location.assign("/dashboard");
  }, [user]);

  return (
    <>
      <PixelLoginPage key={preview.current} preview={preview} />
      {!preview.clean && (
        <nav className={styles.switcher} aria-label="預覽畫面">
          <span>像素登入預覽</span>
          {VIEWS.map(([id, label]) => (
            <a key={id} href={`?view=${id}`} aria-current={preview.current === id ? "page" : undefined}>
              {label}
            </a>
          ))}
        </nav>
      )}
    </>
  );
}
