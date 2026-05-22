from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from src.config import settings
from src.models.openai_types import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    FunctionCall,
    PromptTokensDetails,
    ToolCall,
    UsageInfo,
)
from src.services.claude_runner import ClaudeRunner
from src.services.stream_adapter import adapt_stream
from src.utils.message_formatter import format_messages
from src.utils.model_mapper import resolve_model
from src.utils.multimodal import ImageError, normalize_messages

router = APIRouter()

# Pattern to detect a tool_calls JSON block in Claude's response text.
# Matches a JSON object containing a "tool_calls" key, possibly surrounded
# by whitespace or markdown code fences.
_TOOL_CALLS_RE = re.compile(
    r"(?:```(?:json)?\s*)?"        # optional opening code fence
    r"(\{[^{}]*\"tool_calls\"\s*:\s*\[.*?\]\s*\})"  # the JSON object
    r"(?:\s*```)?"                  # optional closing code fence
    , re.DOTALL
)


def _generate_call_id() -> str:
    """Generate a unique tool call ID like ``call_abc123def456``."""
    return f"call_{uuid.uuid4().hex[:12]}"


def _parse_tool_calls(text: str) -> tuple[list[ToolCall] | None, str | None]:
    """Try to extract tool call JSON from Claude's response text.

    Returns:
        (tool_calls_list, remaining_text)
        - If tool calls found: (list[ToolCall], remaining_text or None)
        - If no tool calls: (None, original_text)
    """
    if not text:
        return None, text

    match = _TOOL_CALLS_RE.search(text)
    if not match:
        return None, text

    json_str = match.group(1)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None, text

    raw_calls = data.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        return None, text

    tool_calls = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name", "")
        arguments = raw.get("arguments", {})
        # arguments must be a JSON-encoded string per OpenAI spec
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)
        tool_calls.append(
            ToolCall(
                id=_generate_call_id(),
                type="function",
                function=FunctionCall(name=name, arguments=arguments),
            )
        )

    if not tool_calls:
        return None, text

    # Extract any text outside the tool call block
    remaining = text[:match.start()] + text[match.end():]
    remaining = remaining.strip()
    # Also strip leftover code fence markers
    remaining = re.sub(r"^```(?:json)?\s*", "", remaining)
    remaining = re.sub(r"\s*```$", "", remaining)
    remaining = remaining.strip() or None

    return tool_calls, remaining


def _merge_allowed_tools(user_tools: str | None, required: str) -> str:
    """Return a comma-separated allowedTools string that includes *required*."""
    items: list[str] = []
    if user_tools:
        items = [t.strip() for t in re.split(r"[,\s]+", user_tools) if t.strip()]
    if required not in items:
        items.append(required)
    return ",".join(items)


# Minimal system prompts the gateway substitutes for the default Claude Code
# agent prompt (~32K tokens of tool definitions + harness instructions).
# Function-calling requests still get the default — they need the harness.
GATEWAY_BASE_SYSTEM = "You are a helpful assistant."
GATEWAY_IMAGE_SYSTEM = (
    "You are a helpful assistant. When a user references a file by name, "
    "use the Read tool to view that file from the current directory. "
    "Never ask the user for file paths."
)


def _assemble_system_prompt(user_system: str | None, has_images: bool) -> str:
    """Build the system prompt sent via ``--system-prompt`` for non-tool calls.

    The gateway preamble replaces Claude Code's default agent prompt so the
    gateway behaves like a generic OpenAI-compatible API.  Any user-supplied
    system content is appended so the user's instructions take precedence by
    recency.
    """
    preamble = GATEWAY_IMAGE_SYSTEM if has_images else GATEWAY_BASE_SYSTEM
    if user_system:
        return f"{preamble}\n\n{user_system}"
    return preamble


def _usage_from_result(result: dict) -> UsageInfo:
    """Map the Claude CLI `usage` block to an OpenAI-style UsageInfo.

    Claude splits input tokens into uncached / cache-creation / cache-read;
    OpenAI's prompt_tokens is the total, with cached tokens reported in
    prompt_tokens_details.  Token counts include the Claude Code CLI's own
    system-prompt overhead, which is genuine usage, not a gateway artifact.
    """
    usage = result.get("usage") or {}
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    prompt = (
        (usage.get("input_tokens", 0) or 0)
        + (usage.get("cache_creation_input_tokens", 0) or 0)
        + cache_read
    )
    completion = usage.get("output_tokens", 0) or 0
    return UsageInfo(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        prompt_tokens_details=(
            PromptTokensDetails(cached_tokens=cache_read) if cache_read else None
        ),
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint backed by Claude Code CLI."""
    model = resolve_model(request.model)

    # Decode any multimodal image content into files the CLI's Read tool can view.
    # normalize_messages flattens list-form content to plain strings in place.
    image_dir: str | None = tempfile.mkdtemp(prefix="ccg-img-")
    try:
        image_count = normalize_messages(request.messages, image_dir)
    except ImageError as exc:
        shutil.rmtree(image_dir, ignore_errors=True)
        return JSONResponse(
            status_code=400,
            content={"error": {"message": str(exc), "type": "invalid_image_content"}},
        )

    # Convert tools to dicts for the formatter
    tools_dicts = None
    if request.tools:
        tools_dicts = [t.model_dump() for t in request.tools]

    prompt, system_prompt = format_messages(request.messages, tools=tools_dicts)

    # Merge system prompt sources: extracted from messages + explicit extension field
    parts: list[str] = []
    if system_prompt:
        parts.append(system_prompt)
    if request.append_system_prompt:
        parts.append(request.append_system_prompt)
    effective_system = "\n".join(parts) if parts else None

    # With images the CLI must run in the image directory with Read enabled;
    # otherwise honor the caller's working_dir / allowed_tools unchanged.
    if image_count > 0:
        working_dir: str | None = image_dir
        allowed_tools = _merge_allowed_tools(request.allowed_tools, "Read")
    else:
        shutil.rmtree(image_dir, ignore_errors=True)
        image_dir = None
        working_dir = request.working_dir or settings.working_dir or None
        allowed_tools = request.allowed_tools

    # Pick the CLI system-prompt strategy and built-in tool filter.  For
    # function-calling requests we keep the default agent harness (needed for
    # tool emulation).  For generic chat we replace the ~32K default prompt
    # with a minimal preamble and disable unused built-in tools.
    if request.tools:
        cli_system_prompt: str | None = None
        cli_append_system_prompt = effective_system
        cli_tools_filter: str | None = None
    else:
        cli_system_prompt = _assemble_system_prompt(effective_system, image_count > 0)
        cli_append_system_prompt = None
        cli_tools_filter = "Read" if image_count > 0 else ""

    if request.stream:
        # On success the temp dir is owned by the stream wrapper's cleanup;
        # if construction fails before that, drop it here.
        try:
            return await _handle_streaming(
                request, model, prompt,
                cli_system_prompt, cli_append_system_prompt,
                working_dir, allowed_tools, cli_tools_filter, image_dir,
            )
        except Exception:
            if image_dir:
                shutil.rmtree(image_dir, ignore_errors=True)
            raise
    try:
        return await _handle_blocking(
            request, model, prompt,
            cli_system_prompt, cli_append_system_prompt,
            working_dir, allowed_tools, cli_tools_filter,
            has_tools=bool(request.tools), has_images=image_count > 0,
        )
    finally:
        if image_dir:
            shutil.rmtree(image_dir, ignore_errors=True)


async def _handle_blocking(
    request: ChatCompletionRequest,
    model: str,
    prompt: str,
    cli_system_prompt: str | None,
    cli_append_system_prompt: str | None,
    working_dir: str | None,
    allowed_tools: str | None,
    tools_filter: str | None,
    has_tools: bool = False,
    has_images: bool = False,
) -> dict:
    """Run blocking claude invocation and return OpenAI-formatted response dict."""
    try:
        if has_tools:
            # The tool path caps turns at 1 to stop Claude self-executing tools;
            # viewing an attached image needs an extra turn for the Read call.
            tool_max_turns = request.max_turns or (3 if has_images else 1)
            result = await ClaudeRunner.run_blocking_with_tools(
                prompt=prompt,
                model=model,
                timeout=settings.claude_cli_timeout,
                max_turns=tool_max_turns,
                working_dir=working_dir,
                session_id=request.session_id,
                permission_mode=request.permission_mode,
                system_prompt=cli_system_prompt,
                append_system_prompt=cli_append_system_prompt,
                allowed_tools=allowed_tools,
                tools_filter=tools_filter,
            )
        else:
            result = await ClaudeRunner.run_blocking(
                prompt=prompt,
                model=model,
                timeout=settings.claude_cli_timeout,
                max_turns=request.max_turns or settings.default_max_turns,
                working_dir=working_dir,
                session_id=request.session_id,
                permission_mode=request.permission_mode,
                system_prompt=cli_system_prompt,
                append_system_prompt=cli_append_system_prompt,
                allowed_tools=allowed_tools,
                tools_filter=tools_filter,
            )
    except (RuntimeError, TimeoutError) as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "cli_error"}},
        )

    content = result.get("result", "") if isinstance(result, dict) else str(result)
    session_id = result.get("session_id") if isinstance(result, dict) else None

    # Try to parse tool calls from the response when tools were provided
    tool_calls = None
    finish_reason = "stop"

    if has_tools and content:
        tool_calls, remaining_text = _parse_tool_calls(content)
        if tool_calls:
            content = remaining_text  # None or leftover text
            finish_reason = "tool_calls"

    response = ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=_usage_from_result(result if isinstance(result, dict) else {}),
    )

    resp_dict = response.model_dump(exclude_none=True)
    if session_id:
        resp_dict["session_id"] = session_id

    return resp_dict


async def _handle_streaming(
    request: ChatCompletionRequest,
    model: str,
    prompt: str,
    cli_system_prompt: str | None,
    cli_append_system_prompt: str | None,
    working_dir: str | None,
    allowed_tools: str | None,
    tools_filter: str | None,
    image_dir: str | None,
) -> StreamingResponse:
    """Run streaming claude invocation and return SSE StreamingResponse."""
    ndjson_stream = ClaudeRunner.run_streaming(
        prompt=prompt,
        model=model,
        max_turns=request.max_turns or settings.default_max_turns,
        working_dir=working_dir,
        session_id=request.session_id,
        permission_mode=request.permission_mode,
        system_prompt=cli_system_prompt,
        append_system_prompt=cli_append_system_prompt,
        allowed_tools=allowed_tools,
        tools_filter=tools_filter,
    )

    sse_stream = adapt_stream(ndjson_stream, model)

    # Defer image temp-dir cleanup until the stream is fully consumed.
    if image_dir:
        async def _stream_with_cleanup():
            try:
                async for chunk in sse_stream:
                    yield chunk
            finally:
                shutil.rmtree(image_dir, ignore_errors=True)

        body = _stream_with_cleanup()
    else:
        body = sse_stream

    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
