"""LLM 接口：OpenAI 兼容客户端的薄封装，外加合规守卫与 token 预算。

- 合规守卫：发出的每条消息都会检查是否包含任何患者标识，一旦发现立即中止（ADR 0001）。
- 预算：累计 token 用量，超过本次启动的预算时抛出 BudgetExceeded，研究循环保存进度后停止。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .errors import BudgetExceeded, ComplianceError

_TOKEN = re.compile(r"[A-Za-z0-9_\-]{4,}")


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{"id","name","arguments"(dict)}]
    tokens: int = 0


class OpenAICompatBackend:
    """DeepSeek、千帆、通义等 OpenAI 兼容服务。"""

    name = "openai-compatible"

    def __init__(self, api_key: str, base_url: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=2)
        self.model = model

    def chat(self, stage, messages, tools=None, json_mode=False) -> LLMResponse:
        kwargs = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        elif json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for c in msg.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": c.id, "name": c.function.name, "arguments": args})
        tokens = getattr(resp.usage, "total_tokens", 0) or 0
        return LLMResponse(content=msg.content or "", tool_calls=calls, tokens=tokens)


class GuardedLLM:
    def __init__(self, backend, sensitive_tokens: set[str], budget: int, used_before_session: int = 0):
        self.backend = backend
        self.sensitive = sensitive_tokens
        self.budget = budget
        self.session_used = 0
        self.total_used = used_before_session
        self.sent_log: list[str] = []  # 测试用：所有发给 LLM 的原文

    @property
    def name(self):
        return self.backend.name

    def _check(self, messages):
        text = json.dumps(messages, ensure_ascii=False, default=str)
        leaked = {t for t in _TOKEN.findall(text) if t in self.sensitive}
        if leaked:
            raise ComplianceError(f"拦截：准备发给 LLM 的内容中含有患者标识（{len(leaked)} 个），已中止")
        self.sent_log.append(text)

    def check_budget(self):
        """在每个阶段开始前调用：阶段内不打断，保证每次启动至少完成一个阶段、恢复后一定有进展。"""
        if self.session_used >= self.budget:
            raise BudgetExceeded()

    def chat(self, stage, messages, tools=None, json_mode=False) -> LLMResponse:
        self._check(messages)
        resp = self.backend.chat(stage, messages, tools=tools, json_mode=json_mode)
        self.session_used += resp.tokens
        self.total_used += resp.tokens
        return resp


def tool_message(call_id: str, result) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, default=str)}


def assistant_message(resp: LLMResponse) -> dict:
    msg = {"role": "assistant", "content": resp.content or ""}
    if resp.tool_calls:
        msg["tool_calls"] = [{"id": c["id"], "type": "function",
                              "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                             for c in resp.tool_calls]
    return msg


def parse_json(text: str):
    """从 LLM 回复中取出 JSON（允许包在 ```json 代码块或前后有说明文字）。"""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None
