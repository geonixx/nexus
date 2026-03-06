"""AI client for Nexus — wraps Anthropic, Gemini, and Ollama with streaming and graceful fallback.

Provider selection (auto-detected from environment):
  1. Anthropic  — set ANTHROPIC_API_KEY
  2. Gemini     — set GOOGLE_API_KEY (fallback when no Anthropic key)
  3. Ollama     — set OLLAMA_MODEL (local, fully offline; no API key required)

All three providers expose the same `stream()` / `complete()` interface.
Tool use (nexus agent run Anthropic path) requires Anthropic.
nexus chat works with all providers (advisory mode for Gemini/Ollama).

Ollama quick-start:
  brew install ollama        # macOS
  ollama pull llama3.2       # download a model (~2 GB)
  ollama serve               # start the daemon (auto-started on macOS)
  export OLLAMA_MODEL=llama3.2
  nexus task suggest 1       # fully local, zero cost
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterator

ANTHROPIC_MODEL = "claude-sonnet-4-6"
GEMINI_MODEL = "gemini-2.5-flash-lite"
OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "llama3.2"
MAX_TOKENS = 1024
CHAT_MAX_TOKENS = 2048


# ── Tool definitions for nexus chat ───────────────────────────────────────────

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tasks",
        "description": (
            "List tasks for the project, optionally filtered by status. "
            "Returns task IDs, statuses, priorities, and titles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "done", "blocked", "cancelled"],
                    "description": "Filter by this status. Omit to list all tasks.",
                },
            },
        },
    },
    {
        "name": "get_task",
        "description": "Get full details for a specific task: description, time entries, estimate vs actual hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The numeric task ID"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "update_task_status",
        "description": "Update a task's status — mark it done, start it, block it, or cancel it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "done", "blocked", "cancelled"],
                },
            },
            "required": ["task_id", "status"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task in the current project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Task priority (default: medium)",
                },
                "description": {"type": "string", "description": "Optional task description"},
                "estimate_hours": {
                    "type": "number",
                    "description": "Optional hour estimate (e.g. 2.0)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "log_time",
        "description": "Log time spent working on a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "hours": {"type": "number", "description": "Hours to log (e.g. 1.5)"},
                "note": {"type": "string", "description": "Optional note about the work done"},
            },
            "required": ["task_id", "hours"],
        },
    },
    {
        "name": "get_project_stats",
        "description": "Get current project statistics: total tasks, completion %, hours logged.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ── Provider base ─────────────────────────────────────────────────────────────

class _AIProvider:
    """Abstract base — subclasses must implement `stream()`."""

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def stream(self, system: str, user: str) -> Iterator[str]:
        raise NotImplementedError

    def complete(self, system: str, user: str) -> str:
        return "".join(self.stream(system, user))


# ── Anthropic provider ────────────────────────────────────────────────────────

class _AnthropicProvider(_AIProvider):
    def __init__(self) -> None:
        self._client = None
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key:
            try:
                import anthropic  # noqa: PLC0415
                self._client = anthropic.Anthropic(api_key=key)
            except ImportError:
                pass

    @property
    def available(self) -> bool:
        return self._client is not None

    def stream(self, system: str, user: str) -> Iterator[str]:
        if not self._client:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it to use AI features: export ANTHROPIC_API_KEY=sk-..."
            )
        import anthropic as _anthropic  # noqa: PLC0415
        try:
            with self._client.messages.stream(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as s:
                yield from s.text_stream
        except _anthropic.AuthenticationError:
            raise RuntimeError("Invalid API key. Check your ANTHROPIC_API_KEY.")
        except _anthropic.BadRequestError as e:
            msg = str(e)
            if "credit" in msg.lower() or "balance" in msg.lower():
                raise RuntimeError("Insufficient API credits. Add credits at console.anthropic.com.")
            raise RuntimeError(f"API request error: {e}")
        except _anthropic.RateLimitError:
            raise RuntimeError("Rate limit hit. Wait a moment and try again.")
        except _anthropic.APIStatusError as e:
            raise RuntimeError(f"API error {e.status_code}: {e.message}")


# ── Gemini provider ───────────────────────────────────────────────────────────

class _GeminiProvider(_AIProvider):
    def __init__(self) -> None:
        self._key = os.environ.get("GOOGLE_API_KEY", "").strip()

    @property
    def available(self) -> bool:
        return bool(self._key)

    def stream(self, system: str, user: str) -> Iterator[str]:
        if not self._key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. "
                "Export it to use AI features: export GOOGLE_API_KEY=..."
            )
        try:
            from google import genai  # noqa: PLC0415
            from google.genai import types  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("google-genai package not installed. Run: uv add google-genai")

        try:
            client = genai.Client(api_key=self._key)
            # Gemini combines system + user into a single prompt; prepend system as context
            full_prompt = f"{system}\n\n{user}" if system else user
            for chunk in client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=full_prompt,
                config=types.GenerateContentConfig(max_output_tokens=MAX_TOKENS),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            msg = str(e)
            # Map common Gemini errors to clean messages
            if "API_KEY_INVALID" in msg or "api key not valid" in msg.lower():
                raise RuntimeError("Invalid API key. Check your GOOGLE_API_KEY.")
            if "quota" in msg.lower() or "resource_exhausted" in msg.lower():
                raise RuntimeError("Gemini quota exceeded. Try again later.")
            if "permission_denied" in msg.lower():
                raise RuntimeError("Permission denied. Verify your GOOGLE_API_KEY has Gemini access.")
            raise RuntimeError(f"Gemini API error: {e}")


# ── Ollama provider ───────────────────────────────────────────────────────────

class _OllamaProvider(_AIProvider):
    """Local Ollama provider — fully offline, no API key required.

    Enabled by setting OLLAMA_MODEL (e.g. 'llama3.2').
    Optionally override the host via OLLAMA_HOST (default: http://localhost:11434).

    Streaming and non-streaming completions are supported.  Tool use is NOT
    supported — nexus agent run and nexus chat require ANTHROPIC_API_KEY.

    The health check (GET /api/tags) uses a hard 3-second timeout so that
    Nexus never hangs waiting for a sleeping daemon.
    """

    def __init__(self) -> None:
        self._model = os.environ.get("OLLAMA_MODEL", "").strip()
        self._host = (
            os.environ.get("OLLAMA_HOST", "").strip() or OLLAMA_DEFAULT_HOST
        ).rstrip("/")
        self._available: bool | None = None  # cached after first probe

    @property
    def available(self) -> bool:
        if not self._model:
            return False
        if self._available is None:
            self._available = self._check_health()
        return self._available

    def _check_health(self) -> bool:
        """Probe GET /api/tags with a 3-second timeout.  Returns False on any error."""
        import urllib.request  # noqa: PLC0415
        import urllib.error    # noqa: PLC0415
        try:
            req = urllib.request.Request(f"{self._host}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_messages(self, system: str, user: str) -> list[dict]:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
        return msgs

    def _url_error_to_runtime(self, exc: Exception) -> RuntimeError:
        return RuntimeError(
            f"Ollama connection error ({self._host}): {exc}. "
            "Is the Ollama daemon running?  Try: ollama serve"
        )

    # ── Core interface ─────────────────────────────────────────────────────────

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield response tokens from Ollama as they arrive (NDJSON streaming)."""
        import json              # noqa: PLC0415
        import urllib.request   # noqa: PLC0415
        import urllib.error     # noqa: PLC0415

        payload = json.dumps({
            "model": self._model,
            "messages": self._build_messages(system, user),
            "stream": True,
        }).encode()

        req = urllib.request.Request(
            f"{self._host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = obj.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        break
        except Exception as exc:
            raise self._url_error_to_runtime(exc) from exc

    def complete(self, system: str, user: str) -> str:
        """Single non-streaming call — used for structured JSON output."""
        import json              # noqa: PLC0415
        import urllib.request   # noqa: PLC0415

        payload = json.dumps({
            "model": self._model,
            "messages": self._build_messages(system, user),
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            f"{self._host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            return body.get("message", {}).get("content", "")
        except Exception as exc:
            raise self._url_error_to_runtime(exc) from exc


# ── Public interface ──────────────────────────────────────────────────────────

class NexusAI:
    """Provider-agnostic AI client.

    Auto-selects backend in priority order:
      1. Anthropic — ANTHROPIC_API_KEY set
      2. Gemini    — GOOGLE_API_KEY set (and no Anthropic key)
      3. Ollama    — OLLAMA_MODEL set and a local daemon reachable (fully offline)

    Always safe to instantiate — check `.available` before using.
    """

    def __init__(self) -> None:
        self._provider: _AIProvider = _AnthropicProvider()
        if not self._provider.available:
            self._provider = _GeminiProvider()
        if not self._provider.available:
            self._provider = _OllamaProvider()

    @property
    def available(self) -> bool:
        return self._provider.available

    @property
    def provider_name(self) -> str:
        if isinstance(self._provider, _AnthropicProvider):
            return "Anthropic"
        if isinstance(self._provider, _GeminiProvider):
            return "Gemini"
        if isinstance(self._provider, _OllamaProvider):
            return f"Ollama ({self._provider._model})"
        return "unknown"

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield text chunks from the model as they arrive."""
        return self._provider.stream(system, user)

    def complete(self, system: str, user: str) -> str:
        """Return the full response (non-streaming). Useful for structured output."""
        return self._provider.complete(system, user)

    @property
    def supports_tools(self) -> bool:
        """True only for Anthropic — tool use is not available via Gemini or Ollama."""
        return isinstance(self._provider, _AnthropicProvider)

    def chat_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_handler: Callable[[str, dict], str],
        *,
        system: str = "",
        max_tokens: int = CHAT_MAX_TOKENS,
    ) -> tuple[str, list[dict]]:
        """Execute one agentic chat turn with tool use (Anthropic only).

        Runs the full tool-use loop for a single user turn:
          send → [tool_use → execute → tool_result → repeat] → final text

        Args:
            messages:     Full conversation history (mutated copy returned).
            tools:        Anthropic tool definitions list.
            tool_handler: Callable(name, inputs) → str result string.
            system:       System prompt for the model.
            max_tokens:   Max tokens per API call.

        Returns:
            (response_text, updated_messages_list)
        """
        if not isinstance(self._provider, _AnthropicProvider):
            raise RuntimeError(
                f"Chat mode requires ANTHROPIC_API_KEY — "
                f"tool use is not available with {self.provider_name}."
            )

        import anthropic as _anthropic  # noqa: PLC0415

        client = self._provider._client
        msgs = list(messages)  # work on a copy

        try:
            while True:
                kwargs: dict[str, Any] = dict(
                    model=ANTHROPIC_MODEL,
                    max_tokens=max_tokens,
                    messages=msgs,
                )
                if system:
                    kwargs["system"] = system
                if tools:
                    kwargs["tools"] = tools

                response = client.messages.create(**kwargs)
                # Serialise the response content for the conversation history.
                # Anthropic content blocks are objects; we convert them to dicts
                # so they survive the round-trip back into messages.create().
                raw_content = response.content
                msgs.append({"role": "assistant", "content": raw_content})

                if response.stop_reason == "tool_use":
                    tool_results = []
                    for block in raw_content:
                        if getattr(block, "type", None) == "tool_use":
                            result_text = tool_handler(block.name, block.input)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result_text,
                                }
                            )
                    msgs.append({"role": "user", "content": tool_results})
                else:
                    # End of turn — collect all text blocks as the final response.
                    text = "".join(
                        getattr(block, "text", "")
                        for block in raw_content
                        if getattr(block, "type", None) == "text"
                    )
                    return text, msgs

        except _anthropic.AuthenticationError:
            raise RuntimeError("Invalid API key. Check your ANTHROPIC_API_KEY.")
        except _anthropic.RateLimitError:
            raise RuntimeError("Rate limit hit. Wait a moment and try again.")
        except _anthropic.APIStatusError as e:
            raise RuntimeError(f"API error {e.status_code}: {e.message}")


# ── Prompt builders ───────────────────────────────────────────────────────────

def suggest_tasks_prompt(project_name: str, project_desc: str, existing_tasks: list[str]) -> tuple[str, str]:
    system = (
        "You are an experienced software project manager. "
        "Your job is to suggest actionable, well-scoped tasks for software projects. "
        "Be specific and practical. Avoid vague or generic suggestions."
    )
    task_list = "\n".join(f"  - {t}" for t in existing_tasks) if existing_tasks else "  (none yet)"
    user = f"""Project: **{project_name}**
Description: {project_desc or "(no description provided)"}

Existing tasks:
{task_list}

Suggest 6–8 new tasks that would meaningfully advance this project.
Do NOT repeat existing tasks. Focus on tasks that are missing or underrepresented.

For each task use this exact format:
**[priority]** Task title (Xh) — one sentence rationale

Where:
- priority is one of: low, medium, high, critical
- Xh is the estimated hours (choose from: 0.5, 1, 2, 3, 5, 8)
- rationale explains why this task matters

Output only the task list — no preamble, no closing remarks."""
    return system, user


def estimate_task_prompt(
    task_title: str,
    task_desc: str,
    similar_tasks: list[tuple[str, float]],
) -> tuple[str, str]:
    system = (
        "You are a software estimation expert. "
        "Give realistic, data-driven hour estimates based on task complexity. "
        "Be concise and direct."
    )
    refs = "\n".join(
        f"  - {title}: {hrs}h actual" for title, hrs in similar_tasks
    ) if similar_tasks else "  (no completed tasks available)"

    user = f"""Please estimate the effort for this task:

**Task:** {task_title}
**Description:** {task_desc or "(no description)"}

Completed tasks for reference:
{refs}

Respond with:
1. **Estimate:** X hours (choose the nearest: 0.5, 1, 1.5, 2, 3, 5, 8, 13)
2. **Reasoning:** 2–3 sentences explaining the estimate
3. **Confidence:** low / medium / high"""
    return system, user


def digest_prompt(
    project_name: str,
    project_desc: str,
    total: int,
    done: int,
    in_prog: int,
    blocked: int,
    hours: float,
    done_titles: list[str],
    in_prog_titles: list[str],
    sprint_name: str | None,
    sprint_goal: str | None,
) -> tuple[str, str]:
    system = (
        "You are a technical project manager writing concise status updates. "
        "Your digests are factual, specific, and professional — never padded. "
        "Write in plain prose, no bullet points."
    )
    pct = int(done / total * 100) if total else 0
    done_list = ", ".join(done_titles[-5:]) if done_titles else "none yet"
    prog_list = ", ".join(in_prog_titles) if in_prog_titles else "none"

    sprint_ctx = ""
    if sprint_name:
        sprint_ctx = f"\nActive sprint: {sprint_name}"
        if sprint_goal:
            sprint_ctx += f" — goal: {sprint_goal}"

    user = f"""Write a 3-paragraph project status digest.

Project: {project_name}
{('Description: ' + project_desc) if project_desc else ''}
Progress: {done}/{total} tasks complete ({pct}%) | {hours:.1f}h logged
In progress: {in_prog} | Blocked: {blocked}{sprint_ctx}

Recently completed: {done_list}
Currently in progress: {prog_list}

Paragraph 1: Overall progress and health (2–3 sentences).
Paragraph 2: What's being worked on and any blockers (2–3 sentences).
Paragraph 3: Next priorities and outlook (1–2 sentences).

Be specific, use the actual task names, stay under 150 words total."""
    return system, user


def sprint_plan_prompt(
    project_name: str,
    backlog: list[tuple[int, str, str, float | None]],  # (id, title, priority, estimate_hours)
    in_progress: list[tuple[int, str]],
    capacity: float | None,
    past_velocity: float | None,
) -> tuple[str, str]:
    system = (
        "You are an agile sprint planning assistant. "
        "Select tasks that fit the sprint capacity, respect priorities, and form a coherent goal. "
        "Be specific about which tasks to include and why. Be concise."
    )

    backlog_lines = "\n".join(
        f"  #{tid}  [{pri}]  {title}  ({est:.1f}h est)" if est else
        f"  #{tid}  [{pri}]  {title}  (no estimate)"
        for tid, title, pri, est in backlog
    )
    in_prog_lines = "\n".join(f"  #{tid}  {title}" for tid, title in in_progress) or "  (none)"

    cap_line = f"Sprint capacity: {capacity:.1f}h" if capacity else "Sprint capacity: unknown"
    vel_line = f"Past average velocity: {past_velocity:.1f}h/sprint" if past_velocity else ""

    user = f"""Help plan the next sprint for **{project_name}**.

{cap_line}
{vel_line}

Currently in progress (carry over):
{in_prog_lines}

Backlog (sorted by entry order):
{backlog_lines}

Recommend which tasks to pull into the sprint. For each recommended task, note:
- Why it should be included (priority, dependencies, value)
- Any risks or unknowns

Then give a one-sentence sprint goal.

Format:
**Recommended tasks:** (list task IDs and titles)
**Sprint goal:** one sentence
**Notes:** any important observations about capacity, risks, or sequencing."""
    return system, user


def standup_prompt(
    project_name: str,
    yesterday_completed: list[str],       # task titles
    yesterday_hours: float,
    in_progress: list[tuple[int, str]],   # (id, title)
    blocked: list[tuple[int, str]],       # (id, title)
    top_next: list[tuple[int, str]],      # (id, title) — highest-priority todo tasks
) -> tuple[str, str]:
    """Prompt for an AI-written daily standup update."""
    system = (
        "You are an engineering assistant generating a concise daily standup update. "
        "Format strictly as three sections: **Yesterday**, **Today**, **Blockers**. "
        "Use actual task names. Be specific and brief — under 80 words total."
    )

    done_list = "\n".join(f"  - {t}" for t in yesterday_completed) or "  (nothing completed)"
    in_prog_list = (
        "\n".join(f"  - #{tid} {title}" for tid, title in in_progress) or "  (none)"
    )
    blocked_list = (
        "\n".join(f"  - #{tid} {title}" for tid, title in blocked) or "  (none)"
    )
    next_list = (
        "\n".join(f"  - #{tid} {title}" for tid, title in top_next) or "  (none queued)"
    )

    user = f"""Write a daily standup update for **{project_name}**.

Yesterday ({yesterday_hours:.1f}h logged):
{done_list}

Currently in progress:
{in_prog_list}

Blocked:
{blocked_list}

Top queued tasks (potential for Today):
{next_list}

Output exactly three bold sections: **Yesterday**, **Today**, **Blockers**. \
Use actual task names. Keep it under 80 words."""
    return system, user


def weekly_report_prompt(
    project_name: str,
    period_label: str,           # e.g. "Mar 1–7, 2026"
    hours_by_day: list[tuple[str, float]],  # [(weekday_abbr, hours), ...]
    total_hours: float,
    tasks_completed: list[str],
    tasks_in_progress: list[str],
    tasks_added: int,
) -> tuple[str, str]:
    system = (
        "You are a technical project manager writing a concise weekly retrospective. "
        "Be specific, honest, and forward-looking. Keep it under 120 words."
    )

    day_breakdown = "  " + "  ".join(
        f"{day}: {h:.1f}h" for day, h in hours_by_day if h > 0
    ) if any(h > 0 for _, h in hours_by_day) else "  (no time logged)"

    done_list = "\n".join(f"  - {t}" for t in tasks_completed) or "  (none)"
    prog_list = ", ".join(tasks_in_progress) or "none"

    user = f"""Write a brief weekly retrospective for **{project_name}**.

Week: {period_label}
Total hours logged: {total_hours:.1f}h
Time by day:
{day_breakdown}

Completed this week:
{done_list}

Still in progress: {prog_list}
New tasks added: {tasks_added}

Write 2–3 sentences covering: what was accomplished, current momentum, and one concrete suggestion for next week."""
    return system, user


def ingest_task_prompt(text: str) -> tuple[str, str]:
    """Parse freeform text (Slack message, support ticket, email) into a structured task.

    Responds with a JSON object only — no markdown fences, no explanation.
    """
    system = (
        "You are a project management assistant that converts freeform text into structured tasks. "
        "Output ONLY valid JSON — no markdown, no explanation, no code fences."
    )
    user = f"""Convert this text into a structured task:

\"{text}\"

Respond with exactly this JSON shape (no extra keys):
{{
  "title": "concise imperative title, max 80 chars",
  "priority": "low|medium|high|critical",
  "description": "cleaned-up description, 1-3 sentences",
  "estimate_hours": <number or null>,
  "rationale": "one sentence explaining the priority choice"
}}

Priority guidelines:
- critical: service is down, data loss, security vulnerability
- high: user-facing bug, blocking other work, customer complaint
- medium: normal feature request or non-blocking bug
- low: nice-to-have, cosmetic, or low-impact improvement

Estimate guidelines (null if genuinely unclear):
- 0.5h: tiny tweak / config change
- 1-2h: small fix, investigation
- 3-5h: medium feature or bug with moderate complexity
- 8+h: large feature or complex refactor"""
    return system, user


def agent_system_prompt(project_name: str, project_desc: str) -> str:
    """System prompt for the autonomous AI scrum master agent."""
    desc_line = f"Description: {project_desc}" if project_desc else ""
    return f"""You are an autonomous AI scrum master for the project **{project_name}**.
{desc_line}

Your job is to review the current state of the project and take intelligent action:

1. START by calling get_project_stats to get an overview, then list_tasks to see all tasks.
2. INVESTIGATE stale work (use get_stale_tasks), blocked tasks, and ready tasks (use get_ready_tasks).
3. LOOK for patterns: overdue in-progress work, tasks stuck in blocked status, dependency bottlenecks.
4. ACT judiciously:
   - Add notes to stale or blocked tasks explaining what needs to happen next.
   - Create new tasks if you spot obvious gaps.
   - Do NOT change task statuses unless clearly warranted and you explain why.
5. CONCLUDE with a plain-language summary of what you found and what actions you took.

Be direct, specific, and efficient. Use task IDs and actual task names in your output.
This is an automated review — the human will see a full transcript of your actions."""


# ── Extended tool set for the agent ───────────────────────────────────────────

AGENT_TOOLS: list[dict] = CHAT_TOOLS + [
    {
        "name": "get_stale_tasks",
        "description": (
            "Find tasks that may be stuck or need attention: "
            "in-progress tasks with no recent activity, long-blocked tasks, "
            "and old backlog items that have never been started."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Flag tasks with no activity in this many days (default: 3).",
                },
            },
        },
    },
    {
        "name": "get_ready_tasks",
        "description": (
            "List TODO and IN_PROGRESS tasks that have all their dependencies satisfied "
            "(i.e., every prerequisite is done or cancelled). These are the tasks that "
            "can be started or continued immediately."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_project_health",
        "description": (
            "Get the project health score (A–F grade, 0–100 score) with a breakdown "
            "of five metrics: completion rate, blocked health, momentum, estimate coverage, "
            "and recent activity."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_task_note",
        "description": "Append a timestamped note to a task. Use this to document follow-ups, blockers, or AI observations on stuck tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The numeric task ID"},
                "note": {"type": "string", "description": "The note text to append"},
            },
            "required": ["task_id", "note"],
        },
    },
    {
        "name": "get_task_dependencies",
        "description": (
            "Get the dependency information for a task: what it depends on (prerequisites) "
            "and what depends on it (downstream tasks)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The numeric task ID"},
            },
            "required": ["task_id"],
        },
    },
]


def offline_agent_prompt(
    project_name: str,
    project_desc: str,
    stats_line: str,
    tasks_ctx: str,
    stale_ctx: str,
    ready_ctx: str,
    valid_task_ids: list[int],
) -> tuple[str, str]:
    """Prompt for offline (Gemini/Ollama) agent review — returns a JSON action plan.

    Instead of iterative tool use, the full project context is injected in one shot
    and the model returns a structured JSON object with observations and actions.

    Action types (conservative, write-safe):
      - add_note:    append a note to an existing task  (task_id must be valid)
      - create_task: create a new task in the project

    Returns:
        (system_prompt, user_prompt) — pass to ai.complete() for a non-streaming call.
    """
    id_list = ", ".join(str(i) for i in sorted(valid_task_ids)) if valid_task_ids else "(none)"
    desc_line = f"Description: {project_desc}" if project_desc else ""

    system = (
        "You are an AI scrum master performing an offline project review. "
        "You will receive a snapshot of the project state and must return a JSON action plan. "
        "Output ONLY valid JSON — no markdown fences, no explanation, no prose before or after."
    )

    user = f"""Review this project snapshot and return a JSON action plan.

Project: {project_name}
{desc_line}
Stats: {stats_line}

Tasks (up to 10 most recent):
{tasks_ctx}

Stale / blocked work:
{stale_ctx}

Ready to start:
{ready_ctx}

Valid task IDs in this project: [{id_list}]

Return exactly this JSON structure (no other text):
{{
  "observations": [
    "observation 1 — specific insight about project state",
    "observation 2",
    "observation 3"
  ],
  "actions": [
    {{"type": "add_note", "task_id": <integer from valid IDs>, "note": "<actionable note text>"}},
    {{"type": "create_task", "title": "<concise imperative title>", "priority": "low|medium|high|critical", "description": "<optional context>"}}
  ]
}}

Rules:
- observations: 2–5 specific insights (not generic praise or filler)
- actions: 0–5 items; only use types "add_note" or "create_task"
- add_note: task_id MUST be an integer from the valid task IDs list above
- create_task: title max 80 chars; priority must be one of low/medium/high/critical
- If no actions are needed, use an empty list: "actions": []
- Do NOT invent task IDs — only use IDs from the valid list above"""

    return system, user


def offline_chat_system_prompt(
    project_name: str,
    project_desc: str,
    stats_line: str,
    tasks_ctx: str,
    stale_ctx: str,
    ready_ctx: str,
) -> str:
    """System prompt for offline (Gemini/Ollama) advisory chat sessions.

    Unlike tool-use chat, this mode is read-only from the model's perspective.
    The model is given a project snapshot up-front and asked to suggest CLI
    commands whenever the user wants to take an action.

    Returns a single str (not a tuple) to pass as the `system` argument to
    `ai.stream()` on every turn. Refresh it with `/context` to pick up changes.
    """
    desc_line = f"Description: {project_desc}" if project_desc else ""
    return f"""You are an AI project advisor embedded in the Nexus CLI for project "{project_name}".
{desc_line}

You are operating in advisory mode (read-only). You cannot take direct actions — instead, suggest
the exact CLI commands the user can run in their terminal to accomplish what they want.

Current project snapshot:
Stats: {stats_line}

Tasks (up to 10 most recent active):
{tasks_ctx}

Stale / blocked work:
{stale_ctx}

Ready to start:
{ready_ctx}

How to help the user:
- Answer questions about the project state using the snapshot above
- Recommend what to work on next and explain your reasoning
- When the user wants to make changes, suggest the exact CLI command
  (e.g. `nexus task done 42`, `nexus task start 7`, `nexus task add --priority high "Fix login bug"`)
- Provide analysis, prioritisation advice, and insights

Important:
- You cannot take actions directly — always suggest CLI commands for changes
- Be concise and practical — the user is a developer working from a terminal
- Use /context to see a refreshed project summary after running commands
- Use actual task IDs and titles from the snapshot when referencing tasks"""


def health_diagnosis_prompt(
    project_name: str,
    grade: str,
    score: int,
    metrics: list[dict],   # [{"name", "score", "max", "detail"}, ...]
    context: dict,         # {"done", "in_progress", "blocked", "todo", "stale", "hours_week"}
) -> tuple[str, str]:
    """Prompt for an AI health diagnosis with actionable recommendations."""
    system = (
        "You are a senior engineering manager reviewing a project health report. "
        "Be direct and specific. Focus on the 1–2 biggest issues and give actionable advice. "
        "Keep the response under 120 words."
    )

    metric_lines = "\n".join(
        f"  {m['name']}: {m['score']}/{m['max']} — {m['detail']}"
        for m in metrics
    )

    user = f"""Project health report for **{project_name}**:

Overall grade: **{grade}** ({score}/100)

Metric breakdown:
{metric_lines}

Context:
  - Done: {context['done']}  In-progress: {context['in_progress']}  Blocked: {context['blocked']}  Todo: {context['todo']}
  - Stale in-progress tasks (no activity 3+ days): {context['stale']}
  - Hours logged this week: {context['hours_week']:.1f}h

In 2–3 sentences: identify the most critical problem areas and give concrete, specific actions \
the team should take this week to improve the health score. Be direct — no preamble."""
    return system, user
