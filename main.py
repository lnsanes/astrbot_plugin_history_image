"""把群聊历史里最近的图片重新附进请求，让模型真的能看到。"""

from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

# 触发词：用户提到「刚才/上面/那张图」这类回溯表述时才加载历史图片
TRIGGERS = (
    "刚才", "刚刚", "上一条", "上面那", "前面那", "那张图", "这个图",
    "这两张", "那两张", "发了什么", "再看", "看看图", "这张",
)

MAX_IMAGES = 3      # 最多带几张，避免 token 爆炸
MAX_MB = 8.0        # 单张上限


@register(
    "astrbot_plugin_history_image",
    "小肥鱼",
    "把历史消息里的图片重新附进请求，让模型能看到刚才发的图",
    "1.0.0",
)
class HistoryImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context

    async def initialize(self) -> None:
        logger.info("[histimg] 已注册：被问「刚才那张图」时会重新加载历史图片")

    @filter.on_llm_request()
    async def inject_recent_images(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        try:
            text = str(getattr(event, "message_str", "") or "")
            if not text or not any(k in text for k in TRIGGERS):
                return

            mgr = getattr(self.context, "message_history_manager", None)
            if mgr is None:
                return

            history = await mgr.get(
                platform_id=event.get_platform_id(),
                user_id=event.unified_msg_origin,
                page_size=20,
            )
            if not history:
                return

            paths = []
            for record in reversed(history):
                content = record.content if isinstance(record.content, dict) else {}
                parts = content.get("message") or []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if str(part.get("type", "")).lower() != "image":
                        continue
                    raw = str(part.get("url", "") or "")
                    if not raw:
                        continue
                    p = Path(raw)
                    if not p.exists():
                        logger.info("[histimg] 文件已不存在: " + raw[:80])
                        continue
                    try:
                        mb = p.stat().st_size / 1024 / 1024
                    except Exception:
                        continue
                    if mb > MAX_MB:
                        logger.info("[histimg] 太大跳过: " + format(mb, ".1f") + " MB")
                        continue
                    if str(p) not in paths:
                        paths.append(str(p))
                if len(paths) >= MAX_IMAGES:
                    break

            if not paths:
                logger.info("[histimg] 没找到可用的历史图片")
                return

            for p in paths[:MAX_IMAGES]:
                req.image_urls.append(p)
            logger.info("[histimg] 已附上 " + str(len(paths[:MAX_IMAGES])) + " 张历史图片")
        except Exception as exc:
            logger.warning("[histimg] 异常: " + repr(exc))
