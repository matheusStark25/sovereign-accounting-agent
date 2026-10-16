import os
import re
from pathlib import Path
from typing import Optional


def _project_root_str() -> str:
    # project root is 2 levels above this file: contabil_agente/services/<file>
    return str(Path(__file__).resolve().parents[2])


def redact_project_root(text: Optional[str]) -> str:
    if not text:
        return ""
    pr = _project_root_str()
    # Replace exact project root occurrences (both backslash and slash variants)
    text = text.replace(pr, "[ROOT]")
    text = text.replace(pr.replace("\\", "/"), "[ROOT]")
    # Also collapse repeated project root mentions
    text = re.sub(r"\[ROOT\](?:[\\/])?", "[ROOT]/", text)
    return text


def compact_stack_text(stack_text: Optional[str], max_frames: int = 5) -> str:
    if not stack_text:
        return ""
    # Find all frame start positions using typical Python trace format
    frame_re = re.compile(
        r"^\s*File \s+\"(?P<path>[^\"]+)\", line (?P<line>\d+), in (?P<func>.+)$", re.M
    )
    matches = list(frame_re.finditer(stack_text))
    if not matches:
        # fallback: take last ~max_frames*3 lines
        lines = stack_text.strip().splitlines()
        tail = lines[-(max_frames * 3) :]
        return redact_project_root("\n".join(tail))

    # take last max_frames matches
    chosen = matches[-max_frames:]
    parts = []
    for i, m in enumerate(chosen):
        start = m.start()
        # end at next chosen start or end of text
        end = chosen[i + 1].start() if i + 1 < len(chosen) else len(stack_text)
        parts.append(stack_text[start:end].rstrip())

    # append exception message (text after the last frame)
    last_end = chosen[-1].end()
    trailing = stack_text[last_end:].strip()
    if trailing:
        parts.append(trailing)

    compacted = "\n\n".join(parts)
    return redact_project_root(compacted)


def canonical_component(
    step_name: Optional[str], error_file: Optional[str], message: Optional[str]
) -> str:
    s = " ".join(
        filter(
            None,
            [str(step_name).lower(), str(error_file).lower(), str(message).lower()],
        )
    )
    if any(k in s for k in ("assinatur", "sign", "signature", "assinatura")):
        return "TOOL_SIGN"
    if any(k in s for k in ("pd", ".pd", "gerar_pd", "pdftool")):
        return "TOOL_PDF"
    if any(k in s for k in ("calc", "calcul", "contabil", "calculator", "calc_tool")):
        return "TOOL_CALC"
    if any(k in s for k in ("rpa", "worker", "sovereign", "task")):
        return "TOOL_RPA"
    # If nothing matched above, attempt to map common engine/test files
    ef = (error_file or "").lower()
    if (
        "run_stress_test.py" in ef
        or "stress" in ef
        or ef.startswith("test_")
        or "test" in ef
    ):
        return "STRESS_HARNESS"
    if any(k in ef for k in ("monitor", "core", "engine")):
        return "CORE_ENGINE"
    return "UNKNOWN_COMPONENT"


def sanitize_event(ev: dict) -> dict:
    # Normalize fields we expect to exist
    ev = dict(ev)
    ef = ev.get("error_file") or ev.get("file") or ""
    # redact project root in file path; if file path contains project root, keep tag
    ef_redacted = redact_project_root(ef)
    # if redaction didn't change and path contains separators, use basename for privacy
    if "[ROOT]" not in ef_redacted:
        try:
            ef_redacted = os.path.basename(ef_redacted) or ef_redacted
        except Exception:
            ef_redacted = ef_redacted
    ev["error_file"] = ef_redacted

    # compact stack trace to last frames
    st = ev.get("stack_trace") or ev.get("trace") or ""
    ev["stack_trace"] = compact_stack_text(st, max_frames=5)

    # canonical component based on step or file or message
    comp = canonical_component(
        ev.get("step"), ef, ev.get("error_message") or ev.get("message")
    )
    # If sanitizer couldn't identify and the original error file indicates test/engine, map accordingly
    if comp == "UNKNOWN_COMPONENT":
        lowef = (ef or "").lower()
        if (
            "run_stress_test.py" in lowef
            or "stress" in lowef
            or lowef.startswith("test_")
            or "test" in lowef
        ):
            comp = "STRESS_HARNESS"
        elif any(k in lowef for k in ("monitor", "core", "engine")):
            comp = "CORE_ENGINE"
    ev["component"] = comp

    return ev
