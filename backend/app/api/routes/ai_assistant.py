from __future__ import annotations

import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.ai.assistant.schemas import AssistantChatRequest, SurfacePublic
from app.ai.assistant.service import chat_stream
from app.ai.assistant.surfaces import get_surfaces_for_user
from app.api.deps import CurrentUser, SessionDep
from app.api.deps.rate_limit import rate_limit_by_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/assistant", tags=["ai-assistant"])


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    # 每一句話會打模型好幾次（讀說明、回答、檢查），一個帳號連打就能把推論排隊塞滿
    dependencies=[
        Depends(rate_limit_by_user(scope="ai-assistant", limit=30, window_seconds=60))
    ],
)
async def assistant_chat(
    request: AssistantChatRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> AsyncIterable[ServerSentEvent]:
    """內建助手的一輪對話，以 Server-Sent Events 逐段送出。

    事件依序是：

    - `status`（`{"tool": …}`）：助手剛用完某個工具，還要再想一輪。
    - `delta`（`{"text": …}`）：正在寫的回答，接在已顯示的文字後面。
    - `reset`（`{}`）：先前的 `delta` 作廢，把已顯示的文字清掉。
    - `final`：完整的回應（`AssistantChatResponse`），一定是最後一則。回答要等寫完
      才能檢查，所以只有它算數；沒通過檢查時 `reply` 是固定文字，要用它換掉
      `delta` 顯示過的內容。
    - `error`（`{}`）：處理到一半出錯，不會再有 `final`。

    回覆下方的頁面按鈕、流程卡與配置規劃都由伺服器依使用者權限組出來，不會由
    模型產生路徑；助手不會替使用者送出或建立任何東西。
    """
    try:
        async for event in chat_stream(request, current_user, session=session):
            kind = event["type"]
            if kind == "final":
                yield ServerSentEvent(event="final", data=event["response"])
            else:
                yield ServerSentEvent(
                    event=kind,
                    data={key: value for key, value in event.items() if key != "type"},
                )
    except Exception:
        # 標頭已經送出，改不了狀態碼：記下來，讓前端知道這一輪不會有回應
        logger.exception("Assistant chat stream failed")
        yield ServerSentEvent(event="error", data={})


@router.get("/surfaces", response_model=list[SurfacePublic])
def list_surfaces(current_user: CurrentUser) -> list[SurfacePublic]:
    """使用者看得到的畫面清單，讓前端把目前路徑對應成 surface_id。

    只回身分允許的畫面，所以這支同時也是權限過濾後的結果。
    """
    return [
        SurfacePublic(
            id=surface.id,
            path=surface.path,
            title=surface.title,
            purpose=surface.purpose,
            when_to_use=surface.when_to_use,
            has_fields=bool(surface.elements),
        )
        for surface in get_surfaces_for_user(current_user)
    ]
