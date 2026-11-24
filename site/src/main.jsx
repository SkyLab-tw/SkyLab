import { createRoot, hydrateRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import PixelLandingPage from "./pixel/PixelLandingPage";
import { createPixelI18n } from "./pixel/i18n";
import { languageFromPath } from "./languages";
import "./site.scss";

/* 官網首頁＝像素版（原版 LandingPage 保留在 classic.html，dev server 才看得到） */
const lang = languageFromPath(window.location.pathname);
const container = document.getElementById("root");
const app = (
  <I18nextProvider i18n={createPixelI18n(lang)}>
    <PixelLandingPage lang={lang} />
  </I18nextProvider>
);

// 正式建置的每個語言頁都是預渲染好的 HTML，直接接手；dev server 沒有預渲染，從頭畫
if (container.firstElementChild) {
  hydrateRoot(container, app);
} else {
  document.documentElement.lang = lang;
  createRoot(container).render(app);
}
