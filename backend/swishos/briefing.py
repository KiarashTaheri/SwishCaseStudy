"""Prose for the two humans: an approval briefing and a crew work order.

This is the only place an LLM is used, and it is used at the rendering boundary
only — computed numbers and flags in, sentences out. It never ranks a plant,
never computes a dollar figure, never decides whether a day is trustworthy and
never forecasts rain. Acting on a recommendation sends a truck and spends about
what it expects to recover, so the number behind it has to be reproducible and
auditable; a sampled token is neither.

What the model is actually for: the same eight numbers mean different things to
an asset manager approving a spend and a crew lead driving to a site, and the
gap between "$25,844 recoverable" and "worth the trip, and here is why" is
writing, not arithmetic. That is a real job and it is the one job here a
deterministic template does adequately but not well.

Two hard rules, enforced on both paths:

1. **Never name a cause for a withheld day.** Inverter fault, curtailment,
   maintenance and metering failure are indistinguishable in this data, and the
   last of those inverts the commercial response. The prompt is given
   signatures, never diagnoses, and is told to report evidence only.
2. **Never fail for want of a key.** With no `ANTHROPIC_API_KEY`, on any API
   error, and on any timeout, the deterministic template is returned and
   `source` says `"template"`. The template is written first and is the thing
   under test; the model is an enhancement to it, not a dependency.

See ASSUMPTIONS.md A3 and DECISIONS.md #10.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

MODEL = "claude-sonnet-5"
MAX_TOKENS = 700
TIMEOUT_SECONDS = 20.0

_STYLE = """You write for an asset manager who approves cleaning spend across 200 \
solar plants, and for the crew leads who do the work. You are given numbers that \
have already been computed. Your job is the wording, not the arithmetic.

Absolute rules:
- Use only the numbers given. Never invent, round differently, recompute or \
extrapolate a figure. If a number is not in the input, it does not exist.
- Never state or imply a cause for a withheld or anomalous reading. Inverter \
faults, curtailment, maintenance and metering errors are indistinguishable in \
this data. Describe the signature ("produced 2% of expected for six days"), \
never the reason.
- No hedging filler, no "it is important to note", no restating the whole input. \
Short declarative sentences.
- British spelling. Dollar figures as given, e.g. $25,844."""


@dataclass(frozen=True)
class Briefing:
    headline: str
    body: str
    source: str  # "anthropic" | "template"


def approval_briefing(facts: dict[str, Any]) -> Briefing:
    """Why this plant is on tomorrow's list — or why it is not.

    `facts` is a PlantRow as the API serves it, so the prose and the table the
    asset manager is reading cannot disagree.
    """
    fallback = _template_briefing(facts)
    prompt = (
        "Write an approval briefing for one plant. Two parts:\n"
        '- "headline": one sentence, at most 14 words, stating the '
        "recommendation and the single number that drives it.\n"
        '- "body": two or three sentences. Say what the margin over break-even '
        "means in practice, name the crew and how many crew-days it takes, and "
        "state plainly how much evidence is behind the estimate. If days were "
        "withheld, say how many and what the readings looked like — never why.\n\n"
        f"Plant data:\n{json.dumps(facts, indent=2, default=str)}\n\n"
        'Reply with JSON only: {"headline": "...", "body": "..."}'
    )
    response = _complete(prompt)
    if response is None:
        return fallback
    try:
        parsed = json.loads(response)
        return Briefing(
            headline=str(parsed["headline"]).strip(),
            body=str(parsed["body"]).strip(),
            source="anthropic",
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        # Malformed output is a template case, not an error case. The briefing
        # is decoration on a decision that has already been made correctly.
        return fallback


def work_order(facts: dict[str, Any]) -> str:
    """Instructions for the crew lead, generated from the approved dispatch.

    Not a second interface: the crew lead's deliverable is a document he can read
    on a phone in a truck, so it is generated output rather than another screen.
    """
    fallback = _template_work_order(facts)
    prompt = (
        "Write a cleaning work order for the crew lead who will drive to this "
        "plant tomorrow. Plain text, no markdown headers, at most 120 words. "
        "Open with the plant name and region. State the crew, the expected "
        "duration in crew-days, and what the plant is currently losing. Close "
        "with one line on what to report back after the wash: the date, and the "
        "first clean performance-ratio reading, because the estimate for this "
        "plant is re-baselined from it.\n\n"
        f"Dispatch data:\n{json.dumps(facts, indent=2, default=str)}"
    )
    response = _complete(prompt)
    return response.strip() if response else fallback


# --------------------------------------------------------------------------- #
# Deterministic fallbacks — the default path, not the degraded one
# --------------------------------------------------------------------------- #


def _template_briefing(facts: dict[str, Any]) -> Briefing:
    name = facts.get("name", facts.get("plant_id", "This plant"))
    status = facts.get("status")
    margin = facts.get("margin_pct")
    recoverable = facts.get("recoverable_usd")
    break_even = facts.get("break_even_soiling_pct")
    soiling = facts.get("soiling_loss_pct")

    if status == "NO_USABLE_READING":
        usable = facts.get("usable_days", 0)
        headline = f"{name}: no estimate — {usable} usable day(s) since the last reset."
        body = (
            f"Cleaning becomes worthwhile above {_pct(break_even)} soiling, but "
            f"there is not enough clean history since "
            f"{facts.get('last_reset_on') or 'commissioning'} to say where this "
            f"plant stands. {_quality_sentence(facts)} It is listed rather than "
            "ranked so it is not mistaken for a plant judged not worth cleaning."
        )
        return Briefing(headline, body, "template")

    if status == "BELOW_BREAK_EVEN":
        days = facts.get("days_to_break_even")
        arrival = (
            f" At {_rate(facts.get('accumulation_rate_pct_per_day'))} it crosses "
            f"in about {days:.1f} days."
            if isinstance(days, (int, float))
            else " No accumulation rate could be measured, so no crossing date is given."
        )
        headline = (
            f"{name}: hold — soiling {_pct(soiling)} against a "
            f"{_pct(break_even)} break-even."
        )
        body = (
            f"Cleaning today would cost {_usd(facts.get('cleaning_cost_usd'))} and "
            f"recover less.{arrival} {_quality_sentence(facts)}"
        )
        return Briefing(headline, body, "template")

    headline = (
        f"{name}: clean — {_pp(margin)} past break-even, "
        f"{_usd(recoverable)} recoverable."
    )
    body = (
        f"Soiling is {_pct(soiling)} against a break-even of {_pct(break_even)}, "
        f"so the {_usd(facts.get('cleaning_cost_usd'))} wash pays for itself and "
        f"returns {_usd(recoverable)} over the {facts.get('days_until_next_reset')} "
        f"days before rain is expected to reset it. {_crew_sentence(facts)} "
        f"{_quality_sentence(facts)}"
    )
    return Briefing(headline, body, "template")


def _template_work_order(facts: dict[str, Any]) -> str:
    snapshot = facts.get("snapshot", facts)
    crew = facts.get("crew_id", "unassigned")
    crew_days = facts.get("crew_days")
    duration = f"{crew_days:.1f} crew-day(s)" if isinstance(crew_days, (int, float)) else "unscheduled"
    return (
        f"CLEANING WORK ORDER — {facts.get('plant_id')}\n"
        f"Dispatch {facts.get('dispatch_id', 'pending')} · for {facts.get('as_of')}\n\n"
        f"Crew {crew}, estimated {duration}.\n\n"
        f"The plant is running {_pct(snapshot.get('soiling_loss_pct'))} below its "
        f"post-wash baseline, against a break-even of "
        f"{_pct(snapshot.get('break_even_soiling_pct'))}. Expected recovery is "
        f"{_usd(snapshot.get('recoverable_usd'))} over "
        f"{snapshot.get('days_until_next_reset')} days at "
        f"${snapshot.get('tariff_per_kwh')}/kWh.\n\n"
        "After the wash, report the completion date and the first full clean "
        "day's performance ratio. The next estimate for this plant is measured "
        "from that reading, so it is the one number this job has to return."
    )


def _crew_sentence(facts: dict[str, Any]) -> str:
    crew = facts.get("suggested_crew")
    if not crew:
        return "No crew is based in this region, so it cannot currently be scheduled."
    return (
        f"Crew {crew['crew_id']} out of {crew['home_base']} would take about "
        f"{crew['crew_days']:.1f} crew-days."
    )


def _quality_sentence(facts: dict[str, Any]) -> str:
    """Evidence, never a diagnosis. See rule 1 in the module docstring."""
    quality = facts.get("quality") or {}
    withheld = quality.get("withheld_days_last_14", 0)
    usable = facts.get("usable_days", 0)
    if not withheld:
        return f"The estimate stands on {usable} usable day(s), with none withheld in the last 14."
    return (
        f"{withheld} of the last 14 readings were withheld as physically "
        f"implausible for soiling and are excluded from the estimate, which "
        f"stands on {usable} usable day(s). The data does not say why, and this "
        "system does not guess."
    )


def _pct(value: Any) -> str:
    return f"{value:.2f}%" if isinstance(value, (int, float)) else "an unknown level of"


def _pp(value: Any) -> str:
    return f"{value:.2f}pp" if isinstance(value, (int, float)) else "an unknown margin"


def _rate(value: Any) -> str:
    return (
        f"{value:.3f}pp/day" if isinstance(value, (int, float)) else "the measured rate"
    )


def _usd(value: Any) -> str:
    return f"${value:,.0f}" if isinstance(value, (int, float)) else "an unknown amount"


# --------------------------------------------------------------------------- #
# The model call
# --------------------------------------------------------------------------- #


def llm_available() -> bool:
    """Whether the enhanced path can run. Reported by `GET /api/health`."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _complete(prompt: str) -> str | None:
    """One model call. Returns None on any failure, having swallowed it.

    Deliberately broad: every failure mode here — no key, no package, network
    down, rate limit, timeout, malformed response — has the same correct
    handling, which is to fall back to the template. Letting any of them reach
    the endpoint would make the dollar figure unavailable because the prose was.
    """
    if not llm_available():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS)
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_STYLE,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
    except Exception:
        return None
