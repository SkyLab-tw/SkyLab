import { useId, useRef, useState } from "react";
import ActionMenu from "../../../components/ActionMenu/ActionMenu";
import ListboxPopover from "../../../components/ListboxPopover/ListboxPopover";
import MIcon from "../../../components/MIcon";
import PasswordInput from "../../../components/PasswordInput/PasswordInput";
import PasswordRules from "../../../components/PasswordRules/PasswordRules";
import NumberInput from "../../../components/NumberInput/NumberInput";
import SegmentedControl from "../../../components/SegmentedControl/SegmentedControl";
import Tabs from "../../../components/Tabs/Tabs";
import Disclosure from "../../../components/Disclosure/Disclosure";
import Switch from "../../../components/Switch/Switch";
import Stepper from "../../../components/Stepper/Stepper";
import ToolbarSearch from "../../../components/DataToolbar/ToolbarSearch";
import MachineKindBadge from "../../../components/MachineKindBadge/MachineKindBadge";
import StatusBadge from "../../../components/StatusBadge/StatusBadge";
import useDialogPresence from "../../../hooks/useDialogPresence";
import { useToast } from "../../../hooks/useToast";
import { Demo, RuleList, Section } from "../DevSection";
import styles from "../DevStylePage.module.scss";

export function ButtonsSection() {
  const toast = useToast();
  const [pinned, setPinned] = useState(true);
  const [spinning, setSpinning] = useState(true);
  const click = () => toast.info("按鈕示範：已點擊");
  return (
    <Section
      id="buttons"
      title="按鈕 Buttons"
      refs={["frontend/src/assets/styles/_mixins.scss", "@include btn-primary / btn-secondary / btn-danger / btn-danger-outline / btn-ghost / btn-icon", "@include btn-icon-secondary", "@include btn-dialog-close"]}
      intro="全站按鈕一律 @include btn-*，不在頁面重抄整組。基底高 36px（行高 22.4＋內距 6×2＋1px 透明框×2）、圓角 8、字級 14/500；hover 一律 :not(:disabled)，disabled 一律 opacity .5。"
    >
      <div className={styles.demoGrid}>
        <Demo label="六款" refs={["btn-primary", "btn-secondary", "btn-danger", "btn-danger-outline", "btn-ghost", "btn-ghost($danger: true)"]} wide>
          <div className={styles.row}>
            <button type="button" className={styles.btnPrimary} onClick={click}><MIcon name="add" size={16} />主要動作</button>
            <button type="button" className={styles.btnSecondary} onClick={click}>一般動作</button>
            <button type="button" className={styles.btnDanger} onClick={click}>確認刪除</button>
            <button type="button" className={styles.btnDangerOutline} onClick={click}><MIcon name="delete_outline" size={16} />刪除</button>
            <button type="button" className={styles.btnGhost} onClick={click}>輔助動作</button>
            <button type="button" className={styles.btnGhostDanger} onClick={click}>移除</button>
          </div>
          <div className={styles.row}>
            <button type="button" className={styles.btnPrimary} disabled>主要動作</button>
            <button type="button" className={styles.btnSecondary} disabled>一般動作</button>
            <button type="button" className={styles.btnDanger} disabled>確認刪除</button>
            <button type="button" className={styles.btnDangerOutline} disabled>刪除</button>
            <button type="button" className={styles.btnGhost} disabled>輔助動作</button>
            <button type="button" className={styles.btnGhostDanger} disabled>移除</button>
          </div>
          <RuleList
            items={[
              "primary 每個畫面至多一顆；danger 只用在確認彈窗／最終確認步驟；頁面內破壞性動作的入口用 danger-outline，點了才進 useConfirm。",
              "頁面差異（寬度、margin、grid 位置）寫在 @include 之後；覆寫 padding 要把 1px 框算進去。",
            ]}
          />
        </Demo>
        <Demo label="圖示鈕 32×32" refs={["btn-icon", "btn-icon($danger: true)", "btn-icon-secondary", "btn-dialog-close"]} note="JSX 必帶 aria-label。表格列的更多操作鈕一律 btn-icon-secondary＋more_vert；btn-dialog-close 只給 Dialog 右上角。">
          <div className={styles.row}>
            <button type="button" className={styles.iconBtn} aria-label="編輯" title="btn-icon" onClick={click}><MIcon name="edit" size={18} /></button>
            <button type="button" className={styles.iconBtnDanger} aria-label="刪除" title="btn-icon($danger: true)" onClick={click}><MIcon name="delete_outline" size={18} /></button>
            <button type="button" className={styles.menuBtn} aria-label="更多操作" title="btn-icon-secondary" onClick={click}><MIcon name="more_vert" size={18} /></button>
            <button type="button" className={styles.dialogClose} aria-label="關閉" title="btn-dialog-close" onClick={click}><MIcon name="close" size={20} /></button>
            <button type="button" className={styles.iconBtn} aria-label="編輯（停用）" disabled><MIcon name="edit" size={18} /></button>
          </div>
        </Demo>
        <Demo label="釘選鈕" refs={["btn-icon", "Sidebar .pinBtn"]} note="已釘選常駐傾斜釘子、無底色；未釘選滑過該列才浮出（佔位、可聚焦）。">
          <div className={styles.pinRow}>
            <span>{pinned ? "已釘選的項目" : "未釘選的項目（滑過看看）"}</span>
            <button
              type="button"
              className={`${styles.pinBtn} ${pinned ? styles.pinBtnPinned : ""}`}
              aria-pressed={pinned}
              aria-label={pinned ? "取消釘選" : "釘選"}
              title={pinned ? "取消釘選" : "釘選"}
              onClick={() => setPinned((v) => !v)}
            >
              <MIcon name="push_pin" size={18} />
            </button>
          </div>
        </Demo>
        <Demo label="處理中圖示" refs={["<MIcon spin />", "global.scss .micon-spin"]} note="處理中狀態的 sync／refresh／autorenew 統一轉速 1s；MIcon 是 classic Material Icons 字型，沒有 progress_activity。">
          <div className={styles.row}>
            <button type="button" className={styles.btnSecondary} onClick={() => setSpinning((v) => !v)}>
              <MIcon name="autorenew" size={16} spin={spinning} />
              {spinning ? "處理中…" : "重新整理"}
            </button>
            <MIcon name="sync" size={20} spin={spinning} />
            <MIcon name="hourglass_empty" size={20} spin={spinning} />
          </div>
        </Demo>
        <Demo label="聊天面板：標頭鈕與輸入框" refs={["chat-header-btn", "chat-composer", "chat-composer($padding: 6px)", "chat-composer-btn", "chat-composer-btn($primary: false)"]} wide note="AI 助手（AiFloatingChat）與檢查表助理（AiJudgePanel）共用；標頭鈕 34px 圓形無底色，輸入框 textarea 隨內容長高、約 7 行停住在框內捲動，聚焦只換邊框色。">
          <div className={styles.row}>
            <button type="button" className={styles.chatHeaderBtn} aria-label="資料來源" title="chat-header-btn" onClick={click}><MIcon name="source" size={20} /></button>
            <button type="button" className={styles.chatHeaderBtn} aria-label="清除對話" title="chat-header-btn" onClick={click}><MIcon name="delete_sweep" size={20} /></button>
            <button type="button" className={styles.chatHeaderBtn} aria-label="停用" disabled><MIcon name="close" size={20} /></button>
          </div>
          <div className={styles.chatComposer}>
            <button type="button" className={styles.chatAttach} aria-label="附件" title="chat-composer-btn($primary: false)" onClick={click}><MIcon name="attach_file" size={20} /></button>
            <textarea rows={1} placeholder="輸入訊息，Shift＋Enter 換行" aria-label="訊息" />
            <button type="button" className={styles.chatSend} aria-label="送出" title="chat-composer-btn" onClick={click}><MIcon name="arrow_upward" size={20} /></button>
          </div>
        </Demo>
      </div>
    </Section>
  );
}

const SEGMENT_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "running", label: "運行中" },
  { value: "stopped", label: "已停止" },
];

export function FormsSection() {
  const [password, setPassword] = useState("Sky");
  const [cores, setCores] = useState(4);
  const [segment, setSegment] = useState("all");
  const [query, setQuery] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [agree, setAgree] = useState(false);
  return (
    <Section
      id="forms"
      title="表單 Forms"
      refs={["@include form-field", "@include form-control", "@include form-control-invalid", "components/PasswordInput", "components/NumberInput", "components/PasswordRules"]}
      intro="欄位一律 .field { @include form-field } ＋ .field input/select/textarea { @include form-control }；控制項固定 36px（內距 6 不是 8），跟按鈕、SegmentedControl、搜尋框同一列才對得齊。欄位怎麼排寫在頁面自己的 grid。"
    >
      <div className={styles.demoGrid}>
        <Demo label="欄位狀態" refs={["form-field", "form-control", ".fieldInvalid.fieldInvalid"]} wide>
          <div className={styles.formGrid}>
            <label className={styles.field}>
              <span>班級名稱</span>
              <input placeholder="例如：資管三甲 作業系統" />
            </label>
            <label className={styles.field}>
              <span>送出時未填（form-control-invalid）</span>
              <input className={styles.fieldInvalid} aria-invalid="true" placeholder="必填" />
              <em className={styles.error}>此欄位必填</em>
            </label>
            <label className={styles.field}>
              <span>唯讀 [readonly]</span>
              <input readOnly value="vm-web-01" />
            </label>
            <label className={styles.field}>
              <span>停用 :disabled</span>
              <input disabled value="LDAP 帳號不可改" />
            </label>
            <label className={styles.field}>
              <span>下拉選單</span>
              <select defaultValue="ubuntu">
                <option value="ubuntu">Ubuntu 24.04</option>
                <option value="debian">Debian 12</option>
                <option value="win">Windows Server 2022</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>日期（鎖 36px）</span>
              <input type="date" defaultValue="2026-10-26" />
            </label>
            <label className={styles.field}>
              <span>密碼（PasswordInput 眼睛鈕，不進 Tab 序）</span>
              <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
              <PasswordRules password={password} />
            </label>
            <label className={styles.field}>
              <span>數字（NumberInput：離開欄位才夾 1–64）</span>
              <NumberInput value={cores} min={1} max={64} step={1} onCommit={setCores} aria-label="CPU 核心數" />
              <span className={styles.hint}>目前定稿值：{cores}</span>
            </label>
            <label className={styles.field}>
              <span>多行文字（固定高：rows 決定，_reset.scss 已全域 resize: none）</span>
              <textarea rows={3} placeholder="備註" />
            </label>
            <label className={styles.field}>
              <span>隨內容長高（field-sizing: content＋max-height，多打幾行看看）</span>
              <textarea className={styles.autoGrow} rows={1} placeholder="回覆學生：一行起跳，最多長到約 5 行，之後在框內捲動" />
              <span className={styles.hint}>聊天輸入框、回覆欄這類「一行起跳」的欄位才用；仍然不寫 resize。</span>
            </label>
          </div>
        </Demo>
        <Demo label="同一列 36px 對齊" refs={["form-control", "SegmentedControl", "ToolbarSearch", "btn-primary", "Switch"]} wide note="欄位、分段切換、搜尋框、按鈕都 36px；搜尋框外框在容器上用 min-height: 36px，不寫 38px。登入／TOTP 的 44px 是例外。">
          <div className={styles.alignRow}>
            <input className={styles.control} placeholder="form-control" aria-label="示範欄位" />
            <SegmentedControl options={SEGMENT_OPTIONS} value={segment} onChange={setSegment} ariaLabel="狀態篩選" />
            <ToolbarSearch value={query} onChange={setQuery} placeholder="搜尋名稱、VMID 或 IP" />
            <button type="button" className={styles.btnPrimary}>新增</button>
            <button type="button" className={styles.btnSecondary}>取消</button>
            <Switch checked={enabled} onChange={setEnabled} label="立即生效的開關" />
          </div>
        </Demo>
        <Demo label="行內收合（補充資訊）" refs={["components/Disclosure", "variant=\"inline\"", "className → font-size"]} note="只有文字＋向下箭頭、沒有框；字級跟著外框，平常淡色、滑過或展開變主色。執行證據、錯誤詳情、工具紀錄、限制與錯誤代碼在用。">
          <Disclosure variant="inline" label="執行證據">
            <p className={styles.hint}>stderr：connection refused（port 3306）</p>
          </Disclosure>
        </Demo>
        <Demo label="收合列（進階設定）" refs={["components/Disclosure", "label", "icon?", "meta?", "bodyClassName"]} wide note="表單底部可以不填的設定收進共用收合列：白底細框、14px／500、右側淡色說明＋箭頭（展開轉半圈），內容接在列下方跟上方欄位對齊。不用瀏覽器原生 ▶ 三角形。建班精靈、首次設定精靈在用。">
          <Disclosure icon="tune" label="進階設定" meta="選填" bodyClassName={styles.formGrid}>
            <label className={styles.field}>
              <span>學期</span>
              <input defaultValue="115-1" />
            </label>
            <label className={styles.field}>
              <span>提前開機</span>
              <select defaultValue="10">
                <option value="0">準時</option>
                <option value="10">10 分鐘</option>
              </select>
            </label>
          </Disclosure>
        </Demo>
        <Demo label="開關與勾選框" refs={["components/Switch", ".checkRow"]} note="一切換就送出 → Switch；按「儲存」才生效 → 勾選框。表格列裡只放開關本體，不寫「啟用」字樣，用 ariaLabel＋title。">
          <div className={styles.stack}>
            <div className={styles.row}>
              <Switch checked={enabled} onChange={setEnabled} ariaLabel="啟用規則" title="啟用規則" />
              <Switch checked={!enabled} onChange={(v) => setEnabled(!v)} label="顯示文字的版本" />
              <Switch checked disabled ariaLabel="停用中的開關" title="停用中" />
            </div>
            <label className={styles.checkRow}>
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              建立後立即開機（按儲存才生效）
            </label>
          </div>
        </Demo>
      </div>
    </Section>
  );
}

export function SegmentSection() {
  const [range, setRange] = useState("7d");
  const [status, setStatus] = useState("pending");
  const [many, setMany] = useState("a");
  return (
    <Section
      id="segment"
      title="分段切換 SegmentedControl"
      refs={["components/SegmentedControl/SegmentedControl.jsx", "options: [{ value, label, icon?, badge?, buttonProps? }]", "quiet"]}
      intro="清單篩選（狀態、類型）、表單選值（申請模式、題型）與檢視選項（時間區間、圖表指標、程式語言）一律用共用 SegmentedControl，固定 36px。清單篩選與表單選值用預設的實心版；檢視選項加 quiet：沒有軌道與陰影、選中段只有主色細框，貼在頁面分頁旁或圖表標頭不搶戲。切換整塊內容的分頁改用 Tabs（下一節）。超過 4 段在 className 加 max-width:100% + overflow-x:auto。"
    >
      <div className={styles.demoGrid}>
        <Demo label="檢視選項：quiet" refs={["quiet", "icon"]} note="時間區間、圖表指標、API 文件的程式語言。切換「看哪一台」這類主要操作（課堂監看切換機器）仍用實心。">
          <SegmentedControl
            quiet
            ariaLabel="日期區間"
            value={range}
            onChange={setRange}
            options={[
              { value: "24h", label: "24 小時", icon: "schedule" },
              { value: "7d", label: "7 天", icon: "date_range" },
              { value: "30d", label: "30 天", icon: "calendar_month" },
            ]}
          />
        </Demo>
        <Demo label="清單篩選：數量徽章＋停用段" refs={["badge", "buttonProps: { disabled }"]}>
          <SegmentedControl
            ariaLabel="審核狀態"
            value={status}
            onChange={setStatus}
            options={[
              { value: "pending", label: "待審核", badge: 3 },
              { value: "approved", label: "已核准", badge: 12 },
              { value: "rejected", label: "已拒絕", badge: 0 },
              { value: "published", label: "發布", buttonProps: { disabled: true, title: "條件未滿足" } },
            ]}
          />
        </Demo>
        <Demo label="窄容器：compact＋fullWidth" refs={["compact", "fullWidth"]} note="240px 以下的窄容器：compact 把各段內距收成 8px，fullWidth 撐滿容器、各段平分。兩個都是元件的 prop，頁面 SCSS 不要再覆寫 .segmentBtn。">
          <div className={styles.narrowBox}>
            <SegmentedControl
              ariaLabel="檢查結果篩選"
              compact
              fullWidth
              value={status === "approved" ? "approved" : "pending"}
              onChange={setStatus}
              options={[
                { value: "pending", label: "待確認", icon: "pending" },
                { value: "approved", label: "已通過", icon: "check_circle" },
              ]}
            />
          </div>
        </Demo>
        <Demo label="5 段以上橫向捲動" refs={["className → overflow-x: auto"]} wide>
          <SegmentedControl
            ariaLabel="背景任務類型"
            className={styles.segmentScroll}
            value={many}
            onChange={setMany}
            options={["a", "b", "c", "d", "e", "f"].map((key, index) => ({
              value: key,
              label: ["全部", "建立", "開關機", "快照", "備份", "還原"][index],
            }))}
          />
        </Demo>
      </div>
    </Section>
  );
}

export function TabsSection() {
  const [detail, setDetail] = useState("proxy");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState("overview");
  const [side, setSide] = useState("rubrics");
  return (
    <Section
      id="tabs"
      title="分頁 Tabs"
      refs={["components/Tabs/Tabs.jsx", "options: [{ value, label, icon?, badge?, buttonProps? }]", "page", "compact", "fullWidth", "@include page-tabs-row"]}
      intro="切換整塊內容一律用 Tabs，分兩種：頁面分頁（page，標題下方切換整頁內容）圖示放進圓角方塊、選中換主色實心；區塊分頁（預設，卡片／側欄裡）沒有軌道，字下一條 2px 主色短指示條。選中的字都加粗到 600（標籤先依粗體預留寬度，切換時不會左右跳）。篩選與選項用 SegmentedControl。role=tablist／tab＋aria-selected，左右鍵、Home／End 切換；放不下自己橫捲。"
    >
      <div className={styles.demoGrid}>
        <Demo label="區塊分頁＋右側篩選與搜尋" refs={["Tabs", "SegmentedControl", "ToolbarSearch"]} wide note="AI 用量監控的呼叫明細（卡片裡的區塊分頁）：分頁換內容、右邊的分段切換只篩目前分頁的清單。徽章 0 也顯示，載入失敗傳「—」。">
          <div className={styles.alignRow}>
            <Tabs
              ariaLabel="呼叫明細"
              value={detail}
              onChange={setDetail}
              options={[
                { value: "models", label: "模型", icon: "model_training", badge: 3 },
                { value: "proxy", label: "金鑰 API 呼叫", icon: "swap_horiz", badge: 128 },
                { value: "template", label: "Template 呼叫", icon: "smart_toy", badge: 0 },
                { value: "users", label: "使用者用量", icon: "groups", badge: "—" },
              ]}
            />
            <SegmentedControl
              ariaLabel="狀態篩選"
              value={status}
              onChange={setStatus}
              options={[
                { value: "all", label: "全部" },
                { value: "success", label: "成功" },
                { value: "error", label: "失敗" },
              ]}
            />
          </div>
        </Demo>
        <Demo label="頁面分頁：page" refs={["page", "icon"]} wide note="標題下方、切換整頁內容的分頁（AI API、帳號設定、資源詳情、班級頁、Gateway、課程內容）。每個分頁都要給 icon；整列往左拉 12px，第一個方塊對齊標題左緣。放在 PageHeader 下方，分頁列 @include page-tabs-row：分頁到內容 12px、標題到分頁 24px。">
          <Tabs
            page
            ariaLabel="資源詳情"
            value={page}
            onChange={setPage}
            options={[
              { value: "overview", label: "總覽", icon: "info" },
              { value: "monitoring", label: "監控", icon: "monitor_heart" },
              { value: "specifications", label: "規格", icon: "tune" },
              { value: "snapshots", label: "快照", icon: "photo_camera" },
            ]}
          />
        </Demo>
        <Demo label="窄容器：compact＋fullWidth" refs={["compact", "fullWidth"]} note="AI 導師檢查 220px 側欄：compact 左右內距 8px、fullWidth 平分。放在有底線的標頭列裡時，頁面讓分頁 align-self: stretch，指示條剛好壓在底線上。">
          <div className={styles.narrowBox}>
            <Tabs
              ariaLabel="側欄分頁"
              compact
              fullWidth
              value={side}
              onChange={setSide}
              options={[
                { value: "rubrics", label: "任務設定", icon: "description" },
                { value: "review", label: "導師核查", icon: "rate_review" },
              ]}
            />
          </div>
        </Demo>
      </div>
    </Section>
  );
}

const LISTBOX_WEEKS = [
  { value: "w1", label: "第 1 週 環境導覽與 SSH 連線", description: "10/21 · 已建立檢查" },
  { value: "w2", label: "第 2 週 Nginx 安裝與虛擬主機", description: "10/28 · 尚未建立檢查" },
  { value: "w3", label: "第 3 週 MariaDB 帳號與資料庫", description: "11/04 · 尚未建立檢查" },
  { value: "w4", label: "第 4 週 PHP-FPM 與網站部署", description: "11/11 · 已建立檢查" },
  { value: "w5", label: "第 5 週 留言板：PHP 連線資料庫", description: "11/18 · 尚未建立檢查" },
  { value: "w6", label: "第 6 週 HTTPS 與憑證", description: "11/25 · 未發布", disabled: true },
  { value: "w7", label: "第 7 週 防火牆與連線規則", description: "12/02 · 尚未建立檢查" },
  { value: "w8", label: "第 8 週 期中實作檢測", description: "12/09 · 尚未建立檢查" },
];

export function ListboxSection() {
  const toast = useToast();
  const anchorRef = useRef(null);
  const listId = useId();
  const [value, setValue] = useState("w4");
  const [open, setOpen] = useState(false);
  const presence = useDialogPresence(open, 130);
  const current = LISTBOX_WEEKS.find((option) => option.value === value);
  return (
    <Section
      id="listbox"
      title="單選清單 ListboxPopover"
      refs={["components/ListboxPopover/ListboxPopover.jsx", "options: [{ value, label, description?, disabled? }]", "hooks/useAnchoredMenu（maxHeight）"]}
      intro="從一串項目挑一個、每項要帶第二行說明（狀態、日期）時用；原生 select 畫不出第二行。開啟時焦點在目前選中那項並捲到中間，上下鍵／Home／End 移動、Enter 選取，Esc 或 Tab 關閉並把焦點交回觸發鈕。下方放不下時清單縮到剩下的空間，不往上推蓋住觸發鈕。"
    >
      <div className={styles.demoGrid}>
        <Demo
          label="換週（AI 導師檢查窄版）"
          refs={['aria-haspopup="listbox"', "aria-expanded", "useDialogPresence(open, 130)"]}
          note="觸發鈕上下鍵直接展開，跟原生下拉一樣。第 6 週示範停用的選項，鍵盤會跳過它。"
        >
          <div className={styles.row}>
            <button
              type="button"
              ref={anchorRef}
              className={styles.btnSecondary}
              aria-haspopup="listbox"
              aria-expanded={open}
              aria-controls={open ? listId : undefined}
              onClick={() => setOpen((next) => !next)}
              onKeyDown={(event) => {
                if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                event.preventDefault();
                setOpen(true);
              }}
            >
              {current?.label}
              <MIcon name="expand_more" size={18} />
            </button>
          </div>
          {presence.open && (
            <ListboxPopover
              id={listId}
              anchorRef={anchorRef}
              ariaLabel="選擇週次"
              options={LISTBOX_WEEKS}
              value={value}
              onSelect={(next) => { setValue(next); toast.info(`示範：切到${LISTBOX_WEEKS.find((option) => option.value === next)?.label}`); }}
              onClose={() => setOpen(false)}
              closing={presence.closing}
            />
          )}
        </Demo>
      </div>
    </Section>
  );
}

export function ActionMenuSection() {
  const toast = useToast();
  const anchorRef = useRef(null);
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const presence = useDialogPresence(open, 130);
  const say = (text) => () => toast.info(`示範：${text}`);
  return (
    <Section
      id="actionmenu"
      title="動作選單 ActionMenu"
      refs={["components/ActionMenu/ActionMenu.jsx", "items: [{ key, label, icon?, onSelect, danger?, disabled?, title?, separatorBefore? }]", "hooks/useAnchoredMenu"]}
      intro="「⋮」按下去的動作選單（例如班級頁首的延長、封存）。更多操作一律用直的 ⋮（more_vert）。開啟時焦點在第一個可用的選項，上下鍵頭尾相接、Home／End，Enter 執行；Esc 或 Tab 關閉並把焦點交回按鈕，Esc 會標成已處理，同頁的批量列不會跟著清除勾選。危險項放最後、前面加分隔線。"
    >
      <div className={styles.demoGrid}>
        <Demo
          label="班級頁首的更多操作"
          refs={['aria-haspopup="menu"', "aria-expanded", "useDialogPresence(open, 130)"]}
          note="觸發鈕用次要鈕做成 36px 正方形，跟旁邊的「返回」鈕同一款。第一項示範停用，鍵盤會跳過它。"
        >
          <div className={styles.row}>
            <button
              type="button"
              ref={anchorRef}
              className={styles.btnSecondary}
              style={{ width: 36, padding: 0 }}
              aria-haspopup="menu"
              aria-expanded={open}
              aria-controls={open ? menuId : undefined}
              aria-label="更多班級操作"
              title="更多班級操作"
              onClick={() => setOpen((next) => !next)}
            >
              <MIcon name="more_vert" size={19} />
            </button>
          </div>
          {presence.open && (
            <ActionMenu
              id={menuId}
              anchorRef={anchorRef}
              ariaLabel="更多班級操作"
              closing={presence.closing}
              onClose={() => setOpen(false)}
              items={[
                { key: "schedule", icon: "edit_calendar", label: "編輯班級與課表", onSelect: say("編輯班級與課表"), disabled: true, title: "送出建機後不能改" },
                { key: "extend", icon: "event_repeat", label: "延長課程日期", onSelect: say("延長課程日期") },
                { key: "archive", icon: "archive", label: "封存並回收", onSelect: say("封存並回收（實際會先跳確認框）"), danger: true, separatorBefore: true },
              ]}
            />
          )}
        </Demo>
      </div>
    </Section>
  );
}

export function StepperSection() {
  const [active, setActive] = useState("env");
  return (
    <Section
      id="stepper"
      title="步驟列 Stepper"
      refs={["components/Stepper/Stepper.jsx", "steps: [{ key, label, done?, disabled? }]", "extras: [{ key, label, icon }]"]}
      intro="流程分頁一律用共用 Stepper（圓點連線），chevron 已淘汰。直接放在頁面上不包卡片、不鋪底色；精靈式流程可跳回已完成步、還不能去的步設 disabled（只擋點擊不淡化）。"
    >
      <Demo label="精靈：1、2 完成、目前第 3 步、第 4 步還不能去；extras 是不算步驟的分頁" plain>
        <Stepper
          ariaLabel="建立班級步驟"
          activeKey={active}
          onSelect={setActive}
          steps={[
            { key: "basic", label: "基本資料", done: true },
            { key: "students", label: "學生名單", done: true },
            { key: "env", label: "上課環境" },
            { key: "review", label: "總覽", disabled: active !== "review" },
          ]}
          extras={[
            { key: "progress", label: "上課進度", icon: "timeline" },
            { key: "ai", label: "AI 導師檢查", icon: "smart_toy" },
          ]}
        />
      </Demo>
      <RuleList
        items={[
          "狀態只靠圓點：未完成＝白底淡藍框編號、已完成＝白底主色框 ✓、目前＝主色實心加光暈；連線兩端都走到了才上主色。",
          "能不能到、打不打勾看已存到後端的進度；換步驟前有未存修改先 confirmLeave()。",
          "手機只留目前步驟的標籤，其他剩圓點；放不下時橫向捲動。",
        ]}
      />
    </Section>
  );
}

const STATUS_BADGES = [
  ["success", "運行中", "--color-success", "check_circle"],
  ["info", "進行中", "--color-info", "sync"],
  ["pending", "待審核", "--color-pending", "person_search"],
  ["danger", "失敗", "--color-danger", "error"],
  ["muted", "已停止", "--color-status-neutral", "hourglass_empty"],
  ["primary", "老師有回覆", "--color-primary", "forum"],
];

export function BadgesSection() {
  return (
    <Section
      id="badges"
      title="徽章 Badges"
      refs={["components/StatusBadge/StatusBadge.jsx", "@include badge-base", "components/MachineKindBadge/MachineKindBadge.jsx"]}
      intro="徽章一律「狀態色 12% 淡底＋狀態色文字」，不加外框；疊在會透出底圖的畫布上時淡底改混 var(--color-surface)。機器來源徽章只用兩群色：我的（info）／別人的（kind-shared），類別交給圖示＋文字。"
    >
      <div className={styles.demoGrid}>
        <Demo label="狀態徽章 StatusBadge" refs={["tone", "icon（選填）", "className 只放位置"]} note="狀態色五款＋primary（非狀態的主色標記）；旁邊已有同義圖示時不帶 icon。">
          <div className={styles.stack}>
            <div className={styles.row}>
              {STATUS_BADGES.map(([tone, label, token]) => (
                <StatusBadge key={tone} tone={tone} title={token}>{label}</StatusBadge>
              ))}
            </div>
            <div className={styles.row}>
              {STATUS_BADGES.map(([tone, label, token, icon]) => (
                <StatusBadge key={tone} tone={tone} icon={icon} title={token}>{label}</StatusBadge>
              ))}
            </div>
          </div>
        </Demo>
        <Demo label="機器來源 MachineKindBadge" refs={["kind", "classRelation", "ownerName", "readOnly"]} note="有擁有者名一律歸「別人的」紫群；淡底 8%。">
          <div className={styles.row}>
            <MachineKindBadge kind="personal" />
            <MachineKindBadge kind="shared" ownerName="王小明" />
            <MachineKindBadge kind="teaching_class" classRelation="student" teachingClassName="作業系統" />
            <MachineKindBadge kind="teaching_class" classRelation="teacher" ownerName="陳同學" />
            <MachineKindBadge kind="quick_practice" />
            <MachineKindBadge kind="course" readOnly />
          </div>
        </Demo>
        <Demo label="實心版（拓撲節點）與行內版" refs={["solid", "plain"]}>
          <div className={styles.row}>
            <MachineKindBadge kind="personal" solid />
            <MachineKindBadge kind="shared" ownerName="王小明" solid />
            <span className={styles.caption}>行內：這台是 <MachineKindBadge kind="course" plain /> 的機器</span>
          </div>
        </Demo>
      </div>
    </Section>
  );
}
