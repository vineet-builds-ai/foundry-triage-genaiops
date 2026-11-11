"""Parser for the agent's prompt file.

The prompt is the agent's behaviour, so it is treated as a structured,
reviewable artefact rather than an opaque blob of prose. Declaring the routing
policy in machine-readable RULE lines buys three things:

  * a code reviewer can diff a policy change and see exactly what moved;
  * the offline backend can execute the declared policy deterministically,
    so the evaluation suite runs with no model and no Azure account;
  * a missing rule is a visible, testable absence rather than a subtle
    behavioural drift.

A real model receives the same file verbatim as its system prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_RULE = re.compile(r"^RULE:\s*(?P<kw>.+?)\s*->\s*(?P<queue>[\w-]+)\s*\|\s*(?P<priority>P[1-4])\s*$")
_FALLBACK = re.compile(
    r"^FALLBACK:\s*(?P<queue>[\w-]+)\s*\|\s*(?P<priority>P[1-4])"
    r"(?:\s*\|\s*needs_human_review\s*=\s*(?P<review>true|false))?\s*$"
)
_FIELDS = re.compile(r"^FIELDS:\s*(?P<fields>.+?)\s*$")


@dataclass(frozen=True)
class Rule:
    keywords: tuple[str, ...]
    queue: str
    priority: str

    def matches(self, text: str) -> str | None:
        """Return the keyword that matched, or None."""
        low = text.lower()
        for kw in self.keywords:
            if kw and kw in low:
                return kw
        return None


@dataclass(frozen=True)
class Fallback:
    queue: str
    priority: str
    needs_human_review: bool = True


@dataclass
class PromptSpec:
    version: int
    raw: str
    required_fields: tuple[str, ...] = ()
    rules: list[Rule] = field(default_factory=list)
    fallback: Fallback | None = None

    @property
    def declared_queues(self) -> set[str]:
        queues = {r.queue for r in self.rules}
        if self.fallback:
            queues.add(self.fallback.queue)
        return queues


def parse_prompt(text: str) -> PromptSpec:
    version = 0
    match = _FRONT_MATTER.match(text)
    if match:
        for line in match.group(1).splitlines():
            if line.strip().startswith("version:"):
                try:
                    version = int(line.split(":", 1)[1].strip())
                except ValueError:
                    version = 0

    rules: list[Rule] = []
    fallback: Fallback | None = None
    required_fields: tuple[str, ...] = ()

    for line in text.splitlines():
        stripped = line.strip()

        rule_match = _RULE.match(stripped)
        if rule_match:
            keywords = tuple(
                kw.strip().lower() for kw in rule_match.group("kw").split("|") if kw.strip()
            )
            rules.append(
                Rule(keywords, rule_match.group("queue"), rule_match.group("priority"))
            )
            continue

        fb_match = _FALLBACK.match(stripped)
        if fb_match:
            review = fb_match.group("review")
            fallback = Fallback(
                fb_match.group("queue"),
                fb_match.group("priority"),
                needs_human_review=(review is None or review == "true"),
            )
            continue

        fields_match = _FIELDS.match(stripped)
        if fields_match:
            required_fields = tuple(
                f.strip() for f in fields_match.group("fields").split(",") if f.strip()
            )

    return PromptSpec(
        version=version,
        raw=text,
        required_fields=required_fields,
        rules=rules,
        fallback=fallback,
    )
