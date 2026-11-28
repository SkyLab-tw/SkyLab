"""畫面的靜態定義形狀，以及前端回報的動態狀態。

刻意不記錄任何版面位置——沒有 bounds、沒有 selector、沒有「右上角」這種描述。
版面還會調整，記了就是等著過期，而且過期的位置比沒有位置更糟：使用者會照著
一個不存在的地方找。element 只用穩定的邏輯 ``id`` 指認，section 是邏輯分組
而不是視覺排列。要在畫面上指出某個地方時，由前端回報它自己的聚光燈步驟
（見 ``schemas.GuideStep``），不從這裡推位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.ai.assistant.catalog import RouteAccess
from app.ai.utils import clean_prompt_text

# element 的語意角色。用途是讓模型知道「這是可以填的還是只能看的」，
# 不描述它長什麼樣子或在哪裡。
ElementRole = Literal[
    "text",
    "number",
    "select",
    "textarea",
    "toggle",
    "date",
    "button",
    "table",
    "chart",
    "list",
    "readonly",
]

MAX_STATE_ELEMENTS = 60


@dataclass(frozen=True)
class ElementSpec:
    """一個欄位或控制項的靜態定義。這一半永遠以伺服器端為準。"""

    id: str
    role: ElementRole
    label: str
    help: str = ""
    constraints: tuple[str, ...] = ()
    # 屬於畫面的哪一組（對應 SurfaceSpec.sections）。是邏輯分組，不是版面位置：
    # 「排程開機與時段」講的是這個設定管什麼，不是它排在畫面第幾塊。
    section: str = ""
    # 敏感欄位連 value 都不收進情境（密碼、金鑰、憑證）
    sensitive: bool = False


@dataclass(frozen=True)
class DialogField:
    """彈出視窗裡的一個欄位：叫什麼、怎麼填。"""

    label: str
    help: str = ""
    required: bool = False


@dataclass(frozen=True)
class DialogSpec:
    """頁面上按了會跳出來的視窗（表單或需要輸入的確認框）。

    ``title`` 與 ``opened_by`` 都是畫面上的原文：使用者照著字找得到，測試也
    拿它們比對語系檔，UI 改字時會紅燈。``opened_by`` 只寫按鈕文字，不寫位置。
    """

    id: str
    title: str
    opened_by: str
    purpose: str
    fields: tuple[DialogField, ...] = ()
    # 送出後會發生什麼、哪些事不可逆
    notes: tuple[str, ...] = ()
    # 同一頁上只有部分身分看得到的視窗（例如教師才有的「轉成範本」）
    access: RouteAccess = "all"


@dataclass(frozen=True)
class RelatedPage:
    """什麼情況下該改去另一頁。``path`` 必須在導覽目錄裡，助手才帶得過去。"""

    path: str
    when: str


@dataclass(frozen=True)
class SurfaceSpec:
    """一個可以被解釋的畫面。

    ``id`` 而不是 ``path`` 當主鍵：同一個路徑上可能有多個畫面（``/my-requests``
    同時是申請列表與申請表單），路徑分不出來。
    """

    id: str
    path: str
    title: str
    purpose: str
    sections: tuple[str, ...] = ()
    elements: tuple[ElementSpec, ...] = field(default=())
    access: RouteAccess = "all"
    # 什麼情況下會需要這一頁（讓使用者判斷「我是不是來對地方」）
    when_to_use: str = ""
    # 這頁主要功能怎麼用，一行一項：「功能：按什麼、會怎樣」
    features: tuple[str, ...] = ()
    dialogs: tuple[DialogSpec, ...] = ()
    related: tuple[RelatedPage, ...] = ()


class ElementState(BaseModel):
    """前端送上來的動態狀態。只有瀏覽器知道這一半。

    值會原樣進 prompt，而且可能是別人填的字（班級名稱、環境名稱），所以先清掉
    能偽造角色邊界的控制 token 與隱形字元。
    """

    value: str | None = Field(default=None, max_length=500)
    error: str | None = Field(default=None, max_length=300)
    disabled: bool | None = None
    disabled_reason: str | None = Field(default=None, max_length=300)

    @field_validator("value", "error", "disabled_reason")
    @classmethod
    def _clean(cls, text: str | None) -> str | None:
        return None if text is None else clean_prompt_text(text)
