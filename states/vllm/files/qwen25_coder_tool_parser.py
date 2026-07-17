"""vLLM tool parser for Qwen2.5-Coder auto tool calls.

Qwen2.5-Coder sometimes emits the intended function-call object as wrappers
such as:

    <tools>
    {"name": "...", "arguments": {...}}
    </tools>

or `<json>...</json>`, fenced JSON, bare JSON, or prose followed by
fenced JSON, instead of the canonical Hermes/Qwen `<tool_call>...</tool_call>`
wrapper.
This parser keeps the normal Hermes/Qwen behavior and normalizes that observed
auto-call shape into `<tool_call>` so vLLM returns OpenAI-compatible
`message.tool_calls` instead of assistant text.
"""

from __future__ import annotations

import json
import re

try:  # vLLM 0.10+
    from vllm.tool_parsers.abstract_tool_parser import ToolParserManager
    from vllm.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
except Exception:  # pragma: no cover - compatibility with older vLLM layouts
    from vllm.entrypoints.openai.tool_parsers.abstract_tool_parser import ToolParserManager
    from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser


_TOOL_BLOCK_RE = re.compile(r"<tools>\s*([\s\S]*?)\s*</tools>", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"<json>\s*([\s\S]*?)\s*</json>", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
_JSON_FENCE_ANYWHERE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _as_tool_call_tags(payload: object) -> str:
    """Render one dict or a list of dicts as Hermes/Qwen tool-call tags."""
    calls = payload if isinstance(payload, list) else [payload]
    rendered: list[str] = []
    for call in calls:
        if (
            isinstance(call, dict)
            and isinstance(call.get("name"), str)
            and "arguments" in call
        ):
            rendered.append(
                "<tool_call>\n"
                + json.dumps(
                    {"name": call["name"], "arguments": call.get("arguments", {})},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n</tool_call>"
            )
    return "\n".join(rendered)


def _normalize_qwen25_auto_tool_call(text: str) -> str:
    """Normalize Qwen2.5-Coder's observed auto tool-call variants."""
    if "<tool_call>" in text:
        return text

    def replace_block(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        try:
            rendered = _as_tool_call_tags(json.loads(body))
        except Exception:
            return match.group(0)
        return rendered or match.group(0)

    normalized = _TOOL_BLOCK_RE.sub(replace_block, text)
    normalized = _JSON_BLOCK_RE.sub(replace_block, normalized)
    if "<tool_call>" in normalized:
        return normalized

    stripped = text.strip()
    candidate_payloads: list[str] = []

    # Exact fenced JSON, e.g. ```json\n{"name":"tool",...}\n```.
    fence_match = _JSON_FENCE_RE.match(stripped)
    if fence_match:
        candidate_payloads.append(fence_match.group(1).strip())

    # Prose followed by a fenced JSON tool request is a common Qwen2.5-Coder
    # auto-tool shape ("I'll use the tool:" + ```json ... ```). vLLM's
    # parser sees the whole message; extract the fenced payload and discard
    # surrounding prose only if the payload is a valid tool-call object/list.
    for match in _JSON_FENCE_ANYWHERE_RE.finditer(text):
        payload = match.group(1).strip()
        if payload not in candidate_payloads:
            candidate_payloads.append(payload)

    # Bare JSON object/list with no prose.
    if stripped.startswith("{") or stripped.startswith("["):
        candidate_payloads.append(stripped)

    for payload_text in candidate_payloads:
        try:
            rendered = _as_tool_call_tags(json.loads(payload_text))
        except Exception:
            continue
        if rendered:
            return rendered

    return text


@ToolParserManager.register_module("qwen25_coder")
class Qwen25CoderToolParser(Hermes2ProToolParser):
    """Hermes/Qwen parser plus Qwen2.5-Coder's `<tools>{...}</tools>` auto shape."""

    def extract_tool_calls(self, model_output, request):  # type: ignore[override]
        return super().extract_tool_calls(
            _normalize_qwen25_auto_tool_call(model_output), request
        )

    def extract_tool_calls_streaming(  # type: ignore[override]
        self,
        previous_text,
        current_text,
        delta_text,
        previous_token_ids,
        current_token_ids,
        delta_token_ids,
        request,
    ):
        # Streaming support is conservative: normalize the accumulated text and
        # let the Hermes streaming parser emit tool-call deltas once enough JSON
        # has arrived. While inside an alternate <tools> block, suppress plain
        # content deltas so callers do not see the raw JSON as assistant text.
        normalized_previous = _normalize_qwen25_auto_tool_call(previous_text)
        normalized_current = _normalize_qwen25_auto_tool_call(current_text)
        normalized_delta = normalized_current[len(normalized_previous) :]
        return super().extract_tool_calls_streaming(
            normalized_previous,
            normalized_current,
            normalized_delta if normalized_delta else "",
            previous_token_ids,
            current_token_ids,
            delta_token_ids,
            request,
        )
