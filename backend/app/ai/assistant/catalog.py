from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.core.permissions import get_user_role, is_admin
from app.models import User
from app.models.user import UserRole

# 存取層級與 App.jsx 的路由守衛一一對應：
#   all     -> 任何登入者
#   learner -> canViewStudentCourses（student 或 admin；老師會被導回首頁）
#   staff   -> canTeach（teacher 或 admin）
#   admin   -> isAdmin（is_superuser 或 role == admin）
RouteAccess = Literal["all", "learner", "staff", "admin"]


@dataclass(frozen=True)
class NavigationRoute:
    path: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    access: RouteAccess = "all"


# 路徑必須實際存在於 frontend/src/App.jsx；
# test_ai_assistant_catalog.py 會逐一比對，改路由時這裡會一起紅燈。
_ROUTES: tuple[NavigationRoute, ...] = (
    NavigationRoute(
        path="/dashboard",
        title="首頁",
        summary="依身分顯示總覽：學生看課程與上課機器，教師看近期班級，管理者看需要處理的事與 AI 維運助手。",
        keywords=(
            "首頁",
            "儀表板",
            "dashboard",
            "總覽",
            "主頁",
            "課程",
            "course",
            "學習",
            "練習",
        ),
    ),
    NavigationRoute(
        path="/courses",
        title="我的課程",
        summary="學生修的課程清單（課程就是學生所在、已經可以上課的班級），進入課程看每週任務與課堂機器。",
        keywords=(
            "我的課程",
            "課程",
            "我的班級",
            "修課",
            "本週任務",
            "課堂機器",
            "my courses",
        ),
        access="learner",
    ),
    NavigationRoute(
        path="/my-resources",
        title="我的資源",
        summary="查看與操作我名下的 VM/LXC 機器。",
        keywords=(
            "我的資源",
            "我的機器",
            "我有哪些機器",
            "my resource",
            "my vm",
            "開機",
            "關機",
        ),
    ),
    NavigationRoute(
        path="/my-requests",
        title="我的申請",
        summary="提交新的機器申請，並追蹤審核進度。",
        keywords=(
            "申請",
            "申請單",
            "我的申請",
            "request",
            "申請 vm",
            "申請 lxc",
            "借機器",
        ),
    ),
    NavigationRoute(
        path="/quick-create",
        title="快速練習",
        summary="從開放快速練習的教學環境立即建立整組機器，免審核，有使用時數限制。",
        keywords=(
            "快速練習",
            "快速建立",
            "quick create",
            "quick practice",
            "練習環境",
            "免審核",
        ),
    ),
    NavigationRoute(
        path="/account",
        title="帳號設定",
        summary="修改個人資料、密碼與兩步驟驗證，調整外觀，或在「關於」送出問題回報與建議。",
        keywords=(
            "帳號",
            "個人設定",
            "改密碼",
            "兩步驟驗證",
            "外觀",
            "回饋",
            "account",
            "profile",
        ),
    ),
    NavigationRoute(
        path="/jobs",
        title="背景任務",
        summary="查看建立、克隆與批次任務的執行進度。",
        keywords=("任務", "job", "背景任務", "進度", "排程"),
    ),
    NavigationRoute(
        path="/firewall",
        title="防火牆",
        summary="以拓撲圖管理機器上網、兩台機器互通與開放服務給外部的連線規則。",
        keywords=(
            "防火牆",
            "firewall",
            "開埠",
            "port",
            "連線規則",
            "上網",
            "互通",
            "開放服務",
        ),
    ),
    NavigationRoute(
        path="/ai-api",
        title="AI API",
        summary="申請 AI API 金鑰、直接跟模型聊天、看串接範例與個人用量。",
        keywords=("ai api", "金鑰", "api key", "token 用量", "llm"),
    ),
    # --- 教師與管理者 ---
    NavigationRoute(
        path="/templates",
        title="機器範本",
        summary="把裝好的機器轉成範本；可見範圍設為「全部可見」後，學生可在申請表單選用。",
        keywords=("範本", "模板", "template", "母範本", "轉範本"),
        access="staff",
    ),
    NavigationRoute(
        path="/class-management",
        title="班級管理",
        summary="列出班級；進入班級管理學生、上課環境、每週內容、上課監看與 AI 導師檢查。",
        keywords=("班級", "課堂", "學生名單", "每週", "上課", "class"),
        access="staff",
    ),
    NavigationRoute(
        path="/class-setup",
        title="一鍵建立班級",
        summary="依序填班級與課表、學生名單、教學環境、每週任務，再送出建機給管理員審核。",
        keywords=("開班", "建立班級", "新增班級", "create class"),
        access="staff",
    ),
    NavigationRoute(
        path="/course-template-management",
        title="教學環境",
        summary="管理教學環境（每位學生最多三台機器的固定配置），提供正式課程、快速練習或兩者使用。",
        keywords=(
            "課程環境",
            "環境範本",
            "教學環境",
            "學習環境",
            "多機環境",
            "快速練習",
        ),
        access="staff",
    ),
    NavigationRoute(
        path="/course-template-management/new",
        title="建立教學環境",
        summary="填寫基本資料與機器配置，發布供正式課程或快速練習使用的教學環境。",
        keywords=("建立教學環境", "新增教學環境"),
        access="staff",
    ),
    # --- 僅管理者 ---
    NavigationRoute(
        path="/resource-mgmt",
        title="資源管理",
        summary="管理全站的機器資源。",
        keywords=("資源管理", "所有資源", "全部機器", "resources"),
        access="admin",
    ),
    NavigationRoute(
        path="/request-review",
        title="申請審核",
        summary="審核使用者送出的機器申請（建立、規格調整等）。",
        keywords=("審核", "審批", "approval", "核准申請"),
        access="admin",
    ),
    NavigationRoute(
        path="/batch-review",
        title="班級審核",
        summary="審核老師為班級送出的整批機器，核准後開始建立。",
        keywords=("班級審核", "審核班級", "班級建機", "批次審核", "批次開通", "batch"),
        access="admin",
    ),
    NavigationRoute(
        path="/gpu-mgmt",
        title="GPU 管理",
        summary="查看 GPU 映射、vGPU 規格與使用狀況。",
        keywords=("gpu", "顯卡", "cuda", "vgpu"),
        access="admin",
    ),
    NavigationRoute(
        path="/monitoring",
        title="資源監控",
        summary="查看叢集與節點負載、吃資源最多的機器、資源警告與疑似挖礦事件。",
        keywords=("監控", "monitoring", "負載", "cpu 使用率", "警告", "挖礦事件"),
        access="admin",
    ),
    NavigationRoute(
        path="/audit",
        title="稽核日誌",
        summary="查詢系統操作紀錄，包含危險操作與登入失敗。",
        keywords=("稽核", "audit", "操作紀錄", "log"),
        access="admin",
    ),
    NavigationRoute(
        path="/feedback",
        title="使用者回饋",
        summary="查看使用者從「帳號設定 › 關於」送出的問題回報與建議，標記已處理或刪除。",
        keywords=("使用者回饋", "回饋", "問題回報", "建議", "意見", "feedback"),
        access="admin",
    ),
    # 原「系統設定」的七個分頁，2026-09 各自升格為系統管理底下的獨立頁面；
    # 舊網址 /settings 預設導到 PVE 管理，所以「系統設定」這個關鍵字留在它身上。
    # 2026-10「節點管理」併入 PVE 管理（舊網址 /nodes 也導過去），節點的關鍵字一起收進來。
    NavigationRoute(
        path="/pve-connections",
        title="PVE 管理",
        summary="管理 Proxmox VE 連線入口、各叢集自己的 pool、Storage 與網段，以及各節點的啟用狀態與放置優先度。",
        keywords=(
            "pve 管理",
            "pve 連線",
            "proxmox",
            "連線",
            "叢集",
            "cluster",
            "pool",
            "系統設定",
            "節點",
            "node",
            "節點管理",
            "優先度",
        ),
        access="admin",
    ),
    NavigationRoute(
        path="/scheduler",
        title="資源排程",
        summary="調整放置、超配與排程開機參數。",
        keywords=(
            "資源排程",
            "排程",
            "超配",
            "放置",
            "placement",
            "overcommit",
            "scheduler",
        ),
        access="admin",
    ),
    # 2026-10「配額」併入治理頁、改名「資源政策」（舊網址 /quotas 導過去），配額的關鍵字一起收進來。
    NavigationRoute(
        path="/governance",
        title="資源政策",
        summary="設定資源警告、TTL 回收、閒置與挖礦偵測等治理政策，以及全域預設的資源上限與個別使用者的配額覆寫。",
        keywords=(
            "資源政策",
            "治理",
            "政策",
            "governance",
            "ttl",
            "閒置",
            "挖礦",
            "快照",
            "配額",
            "quota",
            "上限",
            "限制",
        ),
        access="admin",
    ),
    NavigationRoute(
        path="/ldap",
        title="LDAP",
        summary="設定 LDAP / Active Directory 登入與角色對映。",
        keywords=("ldap", "active directory", "ad 登入", "網域帳號"),
        access="admin",
    ),
    NavigationRoute(
        path="/storage",
        title="儲存空間",
        summary="管理各 Storage 的速度等級、使用者優先度與啟用狀態。",
        keywords=("儲存空間", "storage", "儲存", "磁碟", "nvme", "ssd"),
        access="admin",
    ),
    NavigationRoute(
        path="/ip-management",
        title="IP 管理",
        summary="配置子網與 IP 配發。",
        keywords=("ip", "子網", "subnet", "網段"),
        access="admin",
    ),
    NavigationRoute(
        path="/domain",
        title="網域管理",
        summary="管理 Cloudflare 連線與 DNS 紀錄；這裡的網域就是用網址發布服務時能選的網址結尾。",
        keywords=("網域", "domain", "dns", "cloudflare"),
        access="admin",
    ),
    NavigationRoute(
        path="/gateway",
        title="閘道 VM",
        summary="管理對外流量經過的 Gateway VM：nginx 轉發、WireGuard VPN、HTTPS 憑證與平台入口。",
        keywords=(
            "閘道",
            "gateway",
            "對外流量",
            "nginx",
            "wireguard",
            "vpn",
            "憑證",
            "平台入口",
        ),
        access="admin",
    ),
    NavigationRoute(
        path="/admin",
        title="使用者管理",
        summary="管理使用者帳號、角色、兩步驟驗證、使用者群組（班級）與註冊設定；也是「管理員設定」的入口。",
        keywords=(
            "使用者管理",
            "帳號管理",
            "新增使用者",
            "角色",
            "群組",
            "註冊設定",
            "管理員設定",
            "後台",
            "admin",
        ),
        access="admin",
    ),
    NavigationRoute(
        path="/ai-api-review",
        title="AI API 審核",
        summary="審核使用者的 AI API 申請。",
        keywords=("ai api 審核", "api 申請審核"),
        access="admin",
    ),
    NavigationRoute(
        path="/ai-api-keys",
        title="金鑰管理",
        summary="查看全站已核發的 AI API 金鑰，刪除外洩或濫用的金鑰。",
        keywords=("金鑰管理", "api key 管理"),
        access="admin",
    ),
    NavigationRoute(
        path="/ai-monitoring",
        title="AI 用量監控",
        summary="查看全站 AI API 的呼叫量、Token 用量、錯誤率與各使用者用量（位於「監控與日誌」）。",
        keywords=("ai 用量監控", "ai 監控", "ai 用量", "使用監控", "ai monitoring"),
        access="admin",
    ),
)


def resolve_user_role(user: User) -> UserRole:
    """助手用來判斷可見範圍的角色；超級使用者一律視為 admin（與 isAdmin 守衛一致）。"""
    return UserRole.admin if is_admin(user) else get_user_role(user)


def can_access(access: RouteAccess, role: UserRole) -> bool:
    if access == "all":
        return True
    if access == "learner":
        return role in {UserRole.student, UserRole.admin}
    if access == "staff":
        return role in {UserRole.teacher, UserRole.admin}
    return role == UserRole.admin


def get_routes_for_user(user: User) -> tuple[NavigationRoute, ...]:
    role = resolve_user_role(user)
    return tuple(route for route in _ROUTES if can_access(route.access, role))


def all_routes() -> tuple[NavigationRoute, ...]:
    return _ROUTES


def find_route_by_path(
    path: str, routes: Iterable[NavigationRoute]
) -> NavigationRoute | None:
    target = path.strip()
    for route in routes:
        if route.path == target:
            return route
    return None
