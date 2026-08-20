from __future__ import annotations

"""Compatibility layer for robots.txt parsing.

Production installs Protego (pinned in requirements.txt) for modern robots.txt
semantics. A small local fallback is kept so unit tests and static tooling can
still run in minimal environments where optional dependencies are not installed.
"""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

try:  # pragma: no cover - exercised in the Docker/runtime environment
    from protego import Protego as RobotsParser  # type: ignore
except ImportError:  # pragma: no cover - fallback covered indirectly in CI/minimal envs

    @dataclass(frozen=True)
    class _Rule:
        allow: bool
        pattern: str

        @property
        def specificity(self) -> int:
            # Longest matching rule wins. Wildcards/end markers do not add path
            # specificity, which is sufficient for the rules used by our sources.
            return len(self.pattern.replace("*", "").rstrip("$"))

        def matches(self, path_with_query: str) -> bool:
            end_anchored = self.pattern.endswith("$")
            raw = self.pattern[:-1] if end_anchored else self.pattern
            regex = re.escape(raw).replace(r"\*", ".*")
            if end_anchored:
                regex = f"^{regex}$"
            else:
                regex = f"^{regex}"
            return bool(re.search(regex, path_with_query))

    class RobotsParser:  # minimal Protego-compatible fallback
        def __init__(self, groups: list[tuple[list[str], list[_Rule]]]):
            self._groups = groups

        @classmethod
        def parse(cls, body: str) -> "RobotsParser":
            groups: list[tuple[list[str], list[_Rule]]] = []
            agents: list[str] = []
            rules: list[_Rule] = []
            saw_rule = False

            def flush() -> None:
                nonlocal agents, rules, saw_rule
                if agents:
                    groups.append((agents, rules))
                agents, rules, saw_rule = [], [], False

            for raw_line in body.splitlines():
                line = raw_line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                key, value = (part.strip() for part in line.split(":", 1))
                key = key.lower()
                if key == "user-agent":
                    if saw_rule:
                        flush()
                    agents.append(value.lower())
                elif key in {"allow", "disallow"} and agents:
                    saw_rule = True
                    if value == "" and key == "disallow":
                        continue
                    rules.append(_Rule(allow=key == "allow", pattern=value))
            flush()
            return cls(groups)

        def _rules_for(self, user_agent: str) -> list[_Rule]:
            ua = user_agent.lower()
            matches: list[tuple[int, list[_Rule]]] = []
            for agents, rules in self._groups:
                score = 0
                for token in agents:
                    if token == "*":
                        score = max(score, 1)
                    elif token and token in ua:
                        score = max(score, len(token) + 1)
                if score:
                    matches.append((score, rules))
            if not matches:
                return []
            best = max(score for score, _ in matches)
            merged: list[_Rule] = []
            for score, rules in matches:
                if score == best:
                    merged.extend(rules)
            return merged

        def can_fetch(self, url: str, user_agent: str) -> bool:
            parsed = urlsplit(url)
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            matched = [r for r in self._rules_for(user_agent) if r.matches(target)]
            if not matched:
                return True
            max_specificity = max(r.specificity for r in matched)
            finalists = [r for r in matched if r.specificity == max_specificity]
            # Allow wins on equal specificity.
            return any(r.allow for r in finalists)
