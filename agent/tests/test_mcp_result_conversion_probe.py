"""Spike #674: what litellm 1.105.0's shared MCP result conversion (PR #43089) changes in what DAK's model sees.

DAK's MCP results never reach litellm's MCP handling: ADK's ``McpTool`` dumps the ``CallToolResult`` with
``_dump_mcp_model`` and ``LiteLlm`` JSON-encodes that dict as a ``tool`` message (``_content_to_message_param``).
The shared conversion is ``litellm.proxy._experimental.mcp_server.result_conversion.to_call_tool_result``,
which maps a ``CallToolResult`` to a ``CallToolResult`` for the proxy's MCP wire revision. Its outputs for the
same 3 results are recorded in ``fixtures/litellm_1_105_mcp_result_conversion.json`` (taken from 1.105.0 in an
isolated env, not imported here: it is litellm proxy internals). mcp-server/ is not used.
"""
import asyncio
import json
from pathlib import Path

import pytest
from google.adk.models.lite_llm import _content_to_message_param
from google.adk.tools.mcp_tool.mcp_tool import _dump_mcp_model
from google.genai import types
from mcp.types import CallToolResult, TextContent

from dak_agent.harness import estimate_tokens

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "litellm_1_105_mcp_result_conversion.json").read_text(encoding="utf-8")
)
STRUCTURED = {"city": "Tokyo", "temperature_c": 18.5, "conditions": "cloudy"}
TEXTS = {
    "text": "README.md\nagent/\nmcp-server/",
    "structured": json.dumps(STRUCTURED),
    "error": "ファイルが見つかりません: /workspace/missing.txt",
}


def make_call_tool_results() -> dict[str, CallToolResult]:
    return {
        "text": CallToolResult(content=[TextContent(type="text", text=TEXTS["text"])]),
        "structured": CallToolResult(
            content=[TextContent(type="text", text=TEXTS["structured"])], structured_content=STRUCTURED
        ),
        "error": CallToolResult(content=[TextContent(type="text", text=TEXTS["error"])], is_error=True),
    }


def tool_message_content(result: CallToolResult) -> str:
    """The ``content`` of the tool message DAK sends for ``result`` (same functions as at run time)."""
    dumped = _dump_mcp_model(result)
    dumped.pop("resultType", None)  # on mcp 2.x, McpTool._run_async_impl drops this field before returning
    response = types.FunctionResponse(id="fc-1", name="probe", response=dumped)
    message = asyncio.run(
        _content_to_message_param(types.Content(role="user", parts=[types.Part(function_response=response)]))
    )
    return message["content"]


def converted_message_content(kind: str, compat: str) -> str:
    """The same tool message, had the result gone through the recorded 1.105.0 conversion first."""
    return tool_message_content(CallToolResult.model_validate(FIXTURE["outputs"][kind][compat]))


def test_fixture_was_taken_from_the_same_results():
    assert FIXTURE["litellm_version"] == "1.105.0"
    for kind, result in make_call_tool_results().items():
        assert result.model_dump(mode="json", by_alias=True, exclude_none=True) == FIXTURE["inputs"][kind]


def test_current_tool_message_is_raw_call_tool_result_json():
    for kind, result in make_call_tool_results().items():
        payload = json.loads(tool_message_content(result))
        assert payload["content"] == [{"type": "text", "text": TEXTS[kind]}]
        assert payload["isError"] is (kind == "error")
        assert "resultType" not in payload
    structured = json.loads(tool_message_content(make_call_tool_results()["structured"]))
    assert structured["structuredContent"] == STRUCTURED


@pytest.mark.parametrize("compat", ["legacy", "modern"])
def test_converted_output_keeps_text_and_error_signal(compat):
    for kind in TEXTS:
        payload = json.loads(converted_message_content(kind, compat))
        assert TEXTS[kind] in [block["text"] for block in payload["content"]]
        assert payload["isError"] is (kind == "error")


def test_token_estimates_side_by_side():
    print()
    for kind, result in make_call_tool_results().items():
        current = tool_message_content(result)
        converted = {compat: converted_message_content(kind, compat) for compat in ("legacy", "modern")}
        print(f"{kind:10} current={estimate_tokens(current)} converted_legacy={estimate_tokens(converted['legacy'])} "
              f"converted_modern={estimate_tokens(converted['modern'])} "
              f"same_content={all(current == c for c in converted.values())}")
