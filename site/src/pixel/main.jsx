import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import LandingPage from "./LandingPage";
import { createI18n } from "../i18n";
import { LANGUAGES } from "../languages";
import "../site.scss";

/*
 * 原版介紹頁（已換成像素版首頁，先保留不刪）：只在 dev server 的 classic.html 看得到，不進正式建置。
 * 語言用 ?lang=en／ja 切換；頁面上的語言按鈕會連到正式的像素版各語言首頁。
 */
const requested = new URLSearchParams(window.location.search).get("lang");
const lang = LANGUAGES.some((l) => l.code === requested) ? requested : "zh-TW";
document.documentElement.lang = lang;

createRoot(document.getElementById("root")).render(
  <I18nextProvider i18n={createI18n(lang)}>
    <LandingPage />
  </I18nextProvider>,
);
