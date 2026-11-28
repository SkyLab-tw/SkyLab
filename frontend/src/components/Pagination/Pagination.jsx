import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import MIcon from "../MIcon";
import styles from "./Pagination.module.scss";

/* 頁碼最多畫 7 格（含省略號），超過才出現「前往 __ 頁」 */
const MAX_PAGE_ITEMS = 7;

/* 目前頁（0 起算）→ 要畫的頁碼與省略號。頁數多時固定 7 格：頭尾各一、目前頁前後各一，
   靠近頭尾時改成連續五格，換頁時整列寬度不跳；省略號至少代表兩頁，不會出現「1 … 3」這種只藏一頁的 */
function pageItems(page, totalPages) {
  if (totalPages <= MAX_PAGE_ITEMS) return Array.from({ length: totalPages }, (_, index) => index);
  const last = totalPages - 1;
  if (page <= 3) return [0, 1, 2, 3, 4, "gapEnd", last];
  if (page >= last - 3) return [0, "gapStart", last - 4, last - 3, last - 2, last - 1, last];
  return [0, "gapStart", page - 1, page, page + 1, "gapEnd", last];
}

/* 「前往 __ 頁」：只收數字，按 Enter 或離開欄位就跳；超出範圍夾到第一頁／最後一頁，跳完清空 */
function PageJump({ page, totalPages, onChange, className }) {
  const { t } = useTranslation("components");
  const [draft, setDraft] = useState("");

  function commit() {
    if (!draft) return;
    setDraft("");
    const target = Math.min(Math.max(Number(draft), 1), totalPages) - 1;
    if (target !== page) onChange(target);
  }

  /* 輸入框在句子裡的位置每種語言不同（前往 __ 頁／Go to page __／__ ページへ），用 Trans 嵌進翻譯字串 */
  const input = (
    <input
      type="text"
      inputMode="numeric"
      className={styles.jumpInput}
      value={draft}
      maxLength={String(totalPages).length}
      aria-label={t("Pagination.jumpLabel", { totalPages })}
      onChange={(event) => setDraft(event.target.value.replace(/\D/g, ""))}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        } else if (event.key === "Escape" && draft) {
          event.preventDefault();
          setDraft("");
        }
      }}
      onBlur={commit}
    />
  );

  return (
    <label className={className}>
      <Trans t={t} i18nKey="Pagination.jump" components={{ input }} />
    </label>
  );
}

/**
 * 清單底部的分頁列：左邊「共 N 筆」，右邊上一頁／頁碼／下一頁，頁數多時再加「前往 __ 頁」。
 * 純呈現：page 從 0 起算，分頁邏輯（前端切片或後端 skip/limit）與 info 文案由各頁決定；
 * 按鈕文字、頁碼的無障礙名稱由元件自己翻譯（components 命名空間）。
 * 只有一頁時只剩 info；不想顯示整列的頁面自己包 totalPages > 1。
 * 窄容器（< 520px）頁碼收成「5 / 16」，前往欄一律出現。
 * 使用者、稽核日誌、IP 管理、回饋、AI 金鑰管理、AI API 用量明細共用；新的分頁清單一律用它，不要在頁面裡手抄。
 */
export default function Pagination({ page, totalPages, info, onChange }) {
  const { t } = useTranslation("components");
  const hasPages = totalPages > 1;
  const manyPages = totalPages > MAX_PAGE_ITEMS;

  return (
    <div className={styles.pagination}>
      <div className={styles.row}>
        {info && <span className={styles.info}>{info}</span>}
        {hasPages && (
          <div className={styles.controls}>
            <nav className={styles.nav} aria-label={t("Pagination.navLabel")}>
              <button
                type="button"
                className={styles.arrow}
                disabled={page <= 0}
                aria-label={t("Pagination.prev")}
                title={t("Pagination.prev")}
                onClick={() => onChange(Math.max(page - 1, 0))}
              >
                <MIcon name="chevron_left" size={20} />
              </button>
              <ol className={styles.pages}>
                {pageItems(page, totalPages).map((item) => (
                  <li key={item}>
                    {typeof item === "string" ? (
                      <span className={styles.gap} aria-hidden="true">…</span>
                    ) : (
                      <button
                        type="button"
                        className={item === page ? `${styles.pageBtn} ${styles.pageCurrent}` : styles.pageBtn}
                        aria-current={item === page ? "page" : undefined}
                        aria-label={t("Pagination.page", { page: item + 1 })}
                        onClick={() => item !== page && onChange(item)}
                      >
                        {item + 1}
                      </button>
                    )}
                  </li>
                ))}
              </ol>
              <span className={styles.status}>
                {page + 1} / {totalPages}
              </span>
              <button
                type="button"
                className={styles.arrow}
                disabled={page + 1 >= totalPages}
                aria-label={t("Pagination.next")}
                title={t("Pagination.next")}
                onClick={() => onChange(Math.min(page + 1, totalPages - 1))}
              >
                <MIcon name="chevron_right" size={20} />
              </button>
            </nav>
            <PageJump
              page={page}
              totalPages={totalPages}
              onChange={onChange}
              className={manyPages ? styles.jump : `${styles.jump} ${styles.jumpNarrowOnly}`}
            />
          </div>
        )}
      </div>
    </div>
  );
}
