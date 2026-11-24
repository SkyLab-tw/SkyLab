import { useEffect, useRef } from "react";
import { useAuth } from "../../contexts/AuthContext";
import LoginPage from "./LoginPage";
import styles from "./LoginPreview.module.scss";

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
  const asked = params.get("view");
  const view = VIEWS.some(([id]) => id === asked) ? asked : "login";
  return {
    view,
    methods: {
      ldap: params.get("ldap") === "1",
      // 註冊畫面要後端開放註冊才會出現，預覽時直接假裝開了
      signup_enabled: params.get("signup") === "1" || view === "register",
    },
    user: { email: "student@campus.edu.tw" },
  };
}

/**
 * 登入頁的開發預覽（/dev/login，只在 dev 模式註冊）：
 * 放在所有登入閘門之前，登入中或後端沒開也看得到；左下角切換各畫面（?clean=1 隱藏，截圖用）。
 * 在這裡真的登入成功就轉去首頁，跟正式登入頁一樣。
 */
export default function LoginPreview() {
  const { user } = useAuth();
  const preview = readPreview();
  const clean = new URLSearchParams(window.location.search).get("clean") === "1";
  const hadUser = useRef(Boolean(user));

  useEffect(() => {
    if (user && !hadUser.current) window.location.assign("/dashboard");
  }, [user]);

  return (
    <>
      <LoginPage key={preview.view} preview={preview} />
      {!clean && (
        <nav className={styles.switcher} aria-label="預覽畫面">
          <span>登入頁預覽</span>
          {VIEWS.map(([id, label]) => (
            <a key={id} href={`?view=${id}`} aria-current={preview.view === id ? "page" : undefined}>
              {label}
            </a>
          ))}
        </nav>
      )}
    </>
  );
}
