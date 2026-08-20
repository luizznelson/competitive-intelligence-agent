from src.competitive_intelligence.agent import (
    AgentRateLimitError,
    _unwrap_exception_group,
)


def test_unwrap_exception_group_returns_plain_exception_unchanged():
    exc = AgentRateLimitError("30")
    assert _unwrap_exception_group(exc) is exc


def test_unwrap_exception_group_extracts_single_wrapped_exception():
    # This is exactly what anyio's TaskGroup does: any exception raised inside
    # `async with Client(stdio_client(...))` (agent.py's ask_agent) surfaces
    # from asyncio.run() wrapped in a BaseExceptionGroup, even with only one
    # real error inside. Without unwrapping, `except AgentRateLimitError`
    # in dashboard/app.py never matches, and every error - rate limit, budget,
    # timeout - falls through to the generic "unexpected failure" message.
    inner = AgentRateLimitError("17")
    group = ExceptionGroup("unhandled errors in a TaskGroup", [inner])
    assert _unwrap_exception_group(group) is inner


def test_unwrap_exception_group_handles_nested_groups():
    inner = AgentRateLimitError("5")
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [inner])])
    assert _unwrap_exception_group(nested) is inner
