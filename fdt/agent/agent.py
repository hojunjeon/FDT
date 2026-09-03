"""대화 루프. 설계: docs/03_FDT_설계.md §8.6

사용자 발화 -> (LLM) 툴 선택·파라미터 추출 -> (엔진) 결정론 실행 -> (LLM) 페르소나 코칭 -> 충실도 검사 -> 응답.
"""
from __future__ import annotations

from typing import Any

from fdt.agent.llm import OllamaClient
from fdt.agent.tools import TwinContext


class FdtAgent:
    def __init__(self, client: OllamaClient, ctx: TwinContext, persona: str = "온순냥"):
        self.client, self.ctx, self.persona = client, ctx, persona
        self.history: list[dict[str, Any]] = []

    def ask(self, user_text: str) -> dict[str, Any]:
        """반환: {reply, tool_calls:[{name,args,result}], faithful, fallback, persona}"""
        raise NotImplementedError

    def briefing(self) -> dict[str, Any]:
        """질문 없이 상태 브리핑: 상태 + Safe-to-Spend + 알림 + 리스크 를 한 번에 코칭."""
        raise NotImplementedError
