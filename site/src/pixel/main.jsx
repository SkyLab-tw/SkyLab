import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import { LANGUAGES } from "../languages";
import { createPixelI18n } from "./i18n";
import PixelLandingPage from "./PixelLandingPage";
import "../site.scss";

/* 預覽頁只有一個網址，語言用 ?lang= 切換（正式版換上時再改成各語言的預渲染網址） */
const requested = new URLSearchParams(window.location.search).get("lang");
const lang = LANGUAGES.some((l) => l.code === requested) ? requested : "zh-TW";
document.documentElement.lang = lang;

createRoot(document.getElementById("root")).render(
  <I18nextProvider i18n={createPixelI18n(lang)}>
    <PixelLandingPage lang={lang} />
  </I18nextProvider>,
);
