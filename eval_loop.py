#!/home/tom/projects/playlist-generator/service/.venv/bin/python
"""
Automated Prompt Evaluation & Tuning Loop for Playlist Generator.

Fires a prompt at the playlist generator SSE endpoint, evaluates the output
with OpenAI gpt-4o, and iteratively refines the prompt until quality reaches
an acceptable threshold or max iterations are exhausted.

Usage:
    python eval_loop.py
    python eval_loop.py --prompt "your custom prompt" --threshold 8.0 --max-iter 3
    python eval_loop.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
EVAL_RUNS_DIR = REPO_ROOT / "eval_runs"

DEFAULT_PROMPT = (
    "start quiet and introspective with late-night ambient, build tension through "
    "dark post-rock and krautrock, peak with a crushing drone or doom metal centrepiece, "
    "then slowly dissolve back into silence. Target 90 minutes. "
    "Avoid anything with clean pop vocals."
)

# Diverse prompt suite for --multi mode
# Coverage: 3 metal · 2 goth/darkwave · 2 industrial · 2 non-related
MULTI_PROMPTS: list[tuple[str, str]] = [
    ("ambient_doom_arc", DEFAULT_PROMPT),
    ("thrash_energy", (
        "Pure aggressive thrash metal energy. Start with Bay Area classics, "
        "build through Teutonic thrash, peak with blackened thrash intensity. "
        "Keep it fast, raw, and under 60 minutes. No ballads, no clean singing."
    )),
    ("darkwave_steady", (
        "A steady late-night darkwave and coldwave playlist. Think Clan of Xymox, "
        "Lebanon Hanover, Asylum Party. Maintain a consistent brooding atmosphere "
        "throughout. 70 minutes. No industrial or EBM."
    )),
    ("doom_journey", (
        "An epic doom metal journey: start with traditional doom riffs, descend through "
        "funeral doom and death-doom, reach the darkest point with drone metal, then "
        "slowly ascend back through stoner doom to end on a powerful heavy metal note. "
        "Target 80 minutes."
    )),
    ("black_metal_raw", (
        "Raw second-wave black metal. Scandinavian forest atmosphere, tremolo riffs, "
        "blast beats, howling vocals. No symphonic elements, no polished production, "
        "no clean vocals. Cold, primitive, and unrelenting. 60 minutes."
    )),
    ("industrial_ritual", (
        "A dark industrial ritual from rhythmic noise and EBM into harsh power "
        "electronics and death industrial, ending in cold ambient drones. "
        "Think Throbbing Gristle, Nurse With Wound, early Coil. "
        "No metal, no guitar rock. 75 minutes."
    )),
    ("post_punk_goth", (
        "Classic post-punk into gothic rock. Angular Joy Division-style post-punk opening, "
        "flowing through Bauhaus and The Cure's darker material, closing with desolate "
        "goth rock. No synth-pop, no upbeat new wave. Melancholic throughout. 65 minutes."
    )),
    ("jazz_nocturnal", (
        "A late-night jazz session. Open with cool jazz, drift through modal and hard bop, "
        "end with free jazz tension. Think Miles Davis Kind of Blue era, Coltrane, "
        "Ornette Coleman. Sophisticated and unhurried. No fusion, no smooth jazz. 80 minutes."
    )),
    ("shoegaze_dreampop", (
        "Ethereal shoegaze and dream pop. Start with delicate dream pop, build through "
        "dense shoegaze walls of sound, dissolve into ambient post-rock silence. "
        "Think My Bloody Valentine, Slowdive, Cocteau Twins. 70 minutes."
    )),
]

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_THRESHOLD = 7.5
DEFAULT_MAX_ITER = 3

WEIGHT_ARC = 0.25
WEIGHT_GENRE = 0.20
WEIGHT_TRANSITION = 0.25
WEIGHT_FIDELITY = 0.15
WEIGHT_CURATION = 0.15

OPENAI_MODEL = "gpt-4o"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eval_loop")

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Load variables from service/.env if python-dotenv is unavailable."""
    env_paths = [REPO_ROOT / "service" / ".env", REPO_ROOT / ".env"]
    for env_path in env_paths:
        if not env_path.exists():
            continue
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value


def require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        log.error("Environment variable %s is not set", key)
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# Step 1 — Fire prompt at the playlist generator (SSE)
# ---------------------------------------------------------------------------


async def generate_playlist(
    client: httpx.AsyncClient,
    backend_url: str,
    prompt: str,
    size: int = 25,
) -> dict:
    """POST to /generate-playlist/stream and consume the full SSE stream.

    Returns the playlist dict from the final 'complete' event.
    """
    url = f"{backend_url}/generate-playlist/stream"
    payload = {"prompt": prompt, "size": size}

    log.info("Requesting playlist from %s …", url)

    playlist_data: dict | None = None
    last_stage = ""

    async with client.stream(
        "POST",
        url,
        json=payload,
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0),
    ) as response:
        if response.status_code != 200:
            body = await response.aread()
            raise RuntimeError(
                f"Backend returned HTTP {response.status_code}: {body.decode(errors='replace')}"
            )

        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                json_str = line[len("data:"):].strip()
                if not json_str:
                    continue
                try:
                    event = json.loads(json_str)
                except json.JSONDecodeError:
                    log.warning("Malformed SSE JSON: %s", json_str[:200])
                    continue

                stage = event.get("stage", "")
                message = event.get("message", "")
                progress = event.get("progress", "")

                if stage != last_stage:
                    log.info("  [%s] %s%% — %s", stage, progress, message)
                    last_stage = stage

                if stage == "error":
                    error_detail = event.get("error", message)
                    raise RuntimeError(f"Backend generation error: {error_detail}")

                if stage == "complete":
                    playlist_data = event.get("playlist")

    if playlist_data is None:
        raise RuntimeError("SSE stream ended without a 'complete' event")

    log.info(
        "Received playlist: '%s' — %d tracks",
        playlist_data.get("title", "?"),
        playlist_data.get("playlist_size", len(playlist_data.get("tracks", []))),
    )
    return playlist_data


# ---------------------------------------------------------------------------
# Step 2 — Send the output to OpenAI for evaluation
# ---------------------------------------------------------------------------


def build_evaluation_prompt(original_prompt: str, playlist: dict) -> str:
    """Construct the evaluation system + user message for OpenAI."""
    tracks = playlist.get("tracks", [])
    title = playlist.get("title", "(no title)")

    tracklist_lines: list[str] = []
    for i, t in enumerate(tracks, 1):
        artist = t.get("artist_name", "?")
        ttl = t.get("title", "?")
        genres = ", ".join(t.get("genres", []))
        profile = t.get("profile", {})
        scores = t.get("scores", {})
        explanation = t.get("explanation", "")
        line = (
            f"{i:>2}. {artist} — {ttl}"
            f"  [genres: {genres}]"
            f"  [energy={profile.get('energy','?')}, darkness={profile.get('darkness','?')}, "
            f"tempo={profile.get('tempo','?')}, texture={profile.get('texture','?')}]"
            f"  [semantic={scores.get('semantic','?')}, trajectory={scores.get('trajectory','?')}, "
            f"genre_match={scores.get('genre_match','?')}, total={scores.get('total','?')}]"
        )
        if explanation:
            line += f"\n      Explanation: {explanation}"
        tracklist_lines.append(line)

    tracklist_str = "\n".join(tracklist_lines)

    return f"""\
You are a brutally honest music curator and playlist critic with deep knowledge
of ambient, post-rock, krautrock, doom metal, drone, and underground music.

Evaluate the following playlist that was generated from a user prompt.

=== ORIGINAL USER PROMPT ===
{original_prompt}

=== GENERATED PLAYLIST TITLE ===
{title}

=== FULL ORDERED TRACKLIST ===
{tracklist_str}

=== INSTRUCTIONS ===
Score the playlist on these five dimensions, each 0–10:

1. **Arc coherence** — Does the playlist actually follow the described emotional/sonic arc?
2. **Genre accuracy** — Are the genres correctly matched to the prompt intent?
3. **Transition quality** — Do adjacent tracks flow well together?
4. **Prompt fidelity** — Are the explicit constraints respected (avoidances, duration, mood)?
5. **Curation quality** — Is this a genuinely good playlist a music expert would be proud of?

Also compute an overall weighted score:
  overall = (arc_coherence * 0.25) + (genre_accuracy * 0.20) + (transition_quality * 0.25) + (prompt_fidelity * 0.15) + (curation_quality * 0.15)

Return ONLY valid JSON in this exact shape (no markdown fences, no commentary):
{{
  "scores": {{
    "arc_coherence": <int 0-10>,
    "genre_accuracy": <int 0-10>,
    "transition_quality": <int 0-10>,
    "prompt_fidelity": <int 0-10>,
    "curation_quality": <int 0-10>
  }},
  "overall": <float>,
  "strengths": ["...", "..."],
  "weaknesses": ["...", "..."],
  "per_track_notes": [
    {{"position": 1, "artist": "...", "title": "...", "note": "..."}}
  ],
  "verdict": "one paragraph overall verdict"
}}"""


async def call_openai(
    client: httpx.AsyncClient,
    api_key: str,
    system_msg: str,
    user_msg: str,
    temperature: float = 0.4,
) -> dict:
    """Call OpenAI chat completions and return parsed JSON."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    }

    resp = await client.post(
        OPENAI_API_URL,
        headers=headers,
        json=payload,
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"OpenAI API returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines).strip()

    return json.loads(content)


async def evaluate_playlist(
    client: httpx.AsyncClient,
    api_key: str,
    original_prompt: str,
    playlist: dict,
) -> dict:
    """Run OpenAI evaluation and return the evaluation dict."""
    prompt_text = build_evaluation_prompt(original_prompt, playlist)

    log.info("Sending playlist to OpenAI for evaluation …")
    evaluation = await call_openai(
        client,
        api_key,
        system_msg="You are a music playlist evaluation engine. Return only valid JSON.",
        user_msg=prompt_text,
    )

    # Recompute weighted score to be authoritative
    scores = evaluation.get("scores", {})
    weighted = (
        scores.get("arc_coherence", 0) * WEIGHT_ARC
        + scores.get("genre_accuracy", 0) * WEIGHT_GENRE
        + scores.get("transition_quality", 0) * WEIGHT_TRANSITION
        + scores.get("prompt_fidelity", 0) * WEIGHT_FIDELITY
        + scores.get("curation_quality", 0) * WEIGHT_CURATION
    )
    evaluation["weighted_score"] = round(weighted, 2)

    log.info(
        "Evaluation: arc=%s  genre=%s  transition=%s  fidelity=%s  curation=%s  → weighted=%.2f",
        scores.get("arc_coherence"),
        scores.get("genre_accuracy"),
        scores.get("transition_quality"),
        scores.get("prompt_fidelity"),
        scores.get("curation_quality"),
        weighted,
    )
    return evaluation


# ---------------------------------------------------------------------------
# Step 4 — Generate prompt refinement strategy
# ---------------------------------------------------------------------------


async def generate_refinement(
    client: httpx.AsyncClient,
    api_key: str,
    original_prompt: str,
    current_prompt: str,
    evaluation: dict,
    previous_prompts: list[str],
    iteration: int,
) -> dict:
    """Ask OpenAI how to refine the prompt based on weaknesses."""
    scores = evaluation.get("scores", {})
    weakest = sorted(scores.items(), key=lambda kv: kv[1])[:3]
    weakest_str = ", ".join(f"{k} ({v}/10)" for k, v in weakest)

    history_str = ""
    if previous_prompts:
        history_str = "\n\n=== PREVIOUS PROMPT VARIANTS (do NOT repeat these) ===\n"
        for i, p in enumerate(previous_prompts, 1):
            history_str += f"Variant {i}: {p}\n"

    user_msg = f"""\
I'm using an AI playlist generator that takes natural-language prompts and returns
a curated playlist. The current prompt produced a mediocre result. Help me rewrite
the prompt to get a better playlist.

=== ORIGINAL PROMPT (user's true intent) ===
{original_prompt}

=== CURRENT PROMPT (iteration {iteration}) ===
{current_prompt}

=== EVALUATION ===
{json.dumps(evaluation, indent=2)}

=== WEAKEST DIMENSIONS ===
{weakest_str}
{history_str}

=== INSTRUCTIONS ===
Reason about WHY the playlist failed on the weak dimensions. Then produce a revised
prompt that specifically addresses the weaknesses WITHOUT losing the intent of the
original.

The prompt is consumed by a playlist generator that understands:
- Genre names and sub-genres (be specific: "funeral doom", not just "doom")
- Arc descriptions ("start quiet", "build to", "peak with", "dissolve into")
- Explicit constraints ("avoid X", "no Y", "target N minutes")
- Mood/atmosphere keywords

Return ONLY valid JSON:
{{
  "reasoning": "explanation of what went wrong and why",
  "revised_prompt": "the new full prompt string",
  "changes_made": ["list of specific changes and their rationale"]
}}"""

    log.info("Asking OpenAI for prompt refinement …")
    return await call_openai(
        client,
        api_key,
        system_msg="You are a prompt engineering expert for a music playlist generator. Return only valid JSON.",
        user_msg=user_msg,
        temperature=0.6,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def write_report(run_dir: Path, iterations: list[dict], original_prompt: str) -> None:
    """Write the final Markdown report."""
    best = max(iterations, key=lambda it: it["weighted_score"])

    lines: list[str] = []
    lines.append(f"# Evaluation Report — {run_dir.name}\n")
    lines.append(f"**Original prompt:** {original_prompt}\n")
    lines.append(f"**Iterations:** {len(iterations)}\n")
    lines.append(f"**Best weighted score:** {best['weighted_score']:.2f} (iteration {best['iteration']})\n")
    lines.append("")

    # Summary table
    lines.append("## Iteration Summary\n")
    lines.append("| # | Weighted | Arc | Genre | Transition | Fidelity | Curation |")
    lines.append("|---|----------|-----|-------|------------|----------|----------|")
    for it in iterations:
        s = it["scores"]
        lines.append(
            f"| {it['iteration']} | **{it['weighted_score']:.2f}** "
            f"| {s.get('arc_coherence','-')} "
            f"| {s.get('genre_accuracy','-')} "
            f"| {s.get('transition_quality','-')} "
            f"| {s.get('prompt_fidelity','-')} "
            f"| {s.get('curation_quality','-')} |"
        )
    lines.append("")

    # Prompt variants
    lines.append("## Prompt Variants\n")
    for it in iterations:
        lines.append(f"### Iteration {it['iteration']}\n")
        lines.append(f"```\n{it['prompt']}\n```\n")
        eval_data = it.get("evaluation", {})
        strengths = eval_data.get("strengths", [])
        weaknesses = eval_data.get("weaknesses", [])
        if strengths:
            lines.append("**Strengths:**")
            for s in strengths:
                lines.append(f"- {s}")
            lines.append("")
        if weaknesses:
            lines.append("**Weaknesses:**")
            for w in weaknesses:
                lines.append(f"- {w}")
            lines.append("")

    # Best playlist
    lines.append("## Best Playlist\n")
    best_playlist = best.get("playlist", {})
    lines.append(f"**Title:** {best_playlist.get('title', '?')}\n")
    lines.append(f"**Track count:** {best_playlist.get('playlist_size', len(best_playlist.get('tracks', [])))}\n")
    lines.append("")
    for i, t in enumerate(best_playlist.get("tracks", []), 1):
        lines.append(f"{i:>2}. **{t.get('artist_name','?')}** — {t.get('title','?')}  [{', '.join(t.get('genres', []))}]")
    lines.append("")

    # Verdict
    best_eval = best.get("evaluation", {})
    verdict = best_eval.get("verdict", "")
    if verdict:
        lines.append("## Verdict\n")
        lines.append(f"> {verdict}\n")

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines))
    log.info("Report written to %s", report_path)


def print_summary(iterations: list[dict], threshold: float) -> None:
    """Print a clean summary to stdout."""
    best = max(iterations, key=lambda it: it["weighted_score"])
    passed = best["weighted_score"] >= threshold

    print("\n" + "=" * 60)
    print("  EVALUATION LOOP COMPLETE")
    print("=" * 60)
    print(f"  Iterations run:    {len(iterations)}")
    print(f"  Best score:        {best['weighted_score']:.2f} (iteration {best['iteration']})")
    print(f"  Threshold:         {threshold}")
    print(f"  Result:            {'✓ PASSED' if passed else '✗ BELOW THRESHOLD'}")
    if best.get("playlist", {}).get("title"):
        print(f"  Best playlist:     {best['playlist']['title']}")
    scores = best["scores"]
    print(f"  Breakdown:         arc={scores.get('arc_coherence')}"
          f"  genre={scores.get('genre_accuracy')}"
          f"  transition={scores.get('transition_quality')}"
          f"  fidelity={scores.get('prompt_fidelity')}"
          f"  curation={scores.get('curation_quality')}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Batch aggregation & system diagnosis
# ---------------------------------------------------------------------------


def aggregate_results(prompt_results: dict[str, dict]) -> dict:
    """Aggregate best scores across all prompt runs into per-dimension means."""
    dim_map = {
        "arc_coherence": "arc",
        "genre_accuracy": "genre",
        "transition_quality": "transition",
        "prompt_fidelity": "fidelity",
        "curation_quality": "curation",
    }
    raw: dict[str, list[float]] = {v: [] for v in dim_map.values()}
    weighted_scores: list[float] = []

    for data in prompt_results.values():
        s = data.get("scores", {})
        for k, dim in dim_map.items():
            raw[dim].append(float(s.get(k, 0)))
        weighted_scores.append(float(data.get("weighted_score", 0)))

    means = {k: round(sum(v) / len(v), 2) if v else 0.0 for k, v in raw.items()}
    means["overall"] = (
        round(sum(weighted_scores) / len(weighted_scores), 2) if weighted_scores else 0.0
    )
    return {"means": means, "raw": raw, "per_prompt_weighted": weighted_scores}


async def diagnose_system(
    client: httpx.AsyncClient,
    api_key: str,
    prompt_results: dict[str, dict],
    aggregated: dict,
) -> dict:
    """Ask OpenAI to identify systemic failures and propose concrete code-level fixes."""
    means = aggregated["means"]

    per_prompt_lines: list[str] = []
    for name, data in prompt_results.items():
        s = data.get("scores", {})
        ws = data.get("weighted_score", 0)
        weaknesses = data.get("evaluation", {}).get("weaknesses", [])
        per_prompt_lines.append(
            f"  [{name}] weighted={ws:.2f}  arc={s.get('arc_coherence')}  "
            f"genre={s.get('genre_accuracy')}  transition={s.get('transition_quality')}  "
            f"fidelity={s.get('prompt_fidelity')}  curation={s.get('curation_quality')}\n"
            f"    Weaknesses: {'; '.join(weaknesses[:3])}"
        )

    user_msg = f"""\
You are analyzing a playlist generation system across {len(prompt_results)} diverse prompts.

=== AGGREGATE SCORES ===
Arc coherence:      {means['arc']:.2f}/10
Genre accuracy:     {means['genre']:.2f}/10
Transition quality: {means['transition']:.2f}/10
Prompt fidelity:    {means['fidelity']:.2f}/10
Curation quality:   {means['curation']:.2f}/10
Overall weighted:   {means['overall']:.2f}/10

=== PER-PROMPT BREAKDOWN ===
{chr(10).join(per_prompt_lines)}

=== SYSTEM ARCHITECTURE ===
Pipeline: semantic embedding search → 4D trajectory scoring → beam search sequencing
Scoring: semantic*0.25 + trajectory*0.35 + transition*0.20 + bridge_bonus*0.05 - gravity_penalty*0.15
Trajectory dimensions: energy, darkness, tempo, texture (0-1 each)
Candidate pool: single semantic query, re-scored per playlist position
Sequencing: beam search with dual-anchor gravity (prompt centroid + scene centroid)
Eval weights: arc*{WEIGHT_ARC} + genre*{WEIGHT_GENRE} + transition*{WEIGHT_TRANSITION} + fidelity*{WEIGHT_FIDELITY} + curation*{WEIGHT_CURATION}

=== TASK ===
Identify SYSTEMIC problems — issues that appear across MULTIPLE prompts.
Do NOT suggest rewriting prompts. Diagnose the SYSTEM.

Failure categories:
- ARC_FAILURE: energy/darkness arc not manifesting in track ordering
- GENRE_DRIFT: wrong genres selected; semantic similarity overpowering genre constraints
- TRANSITION_WEAKNESS: harsh jumps between tracks; missing bridge tracks
- CONSTRAINT_VIOLATION: explicit exclusions ignored ("no clean vocals", "no industrial", etc.)
- CURATION_FLATNESS: safe/obvious picks; lacking depth or intentionality

For each issue propose a CONCRETE fix as a pseudo-diff or weight/config change.

Return ONLY valid JSON (no markdown fences):
{{
  "systemic_issues": [
    {{
      "category": "ARC_FAILURE|GENRE_DRIFT|TRANSITION_WEAKNESS|CONSTRAINT_VIOLATION|CURATION_FLATNESS",
      "severity": "HIGH|MEDIUM|LOW",
      "description": "what is wrong and why",
      "evidence": ["prompt_name: specific observation"],
      "proposed_fix": {{
        "description": "what to change and where in the codebase",
        "diff": "pseudo-diff showing the change",
        "expected_impact": "which eval dimensions improve and by how much"
      }}
    }}
  ],
  "priority_order": ["issue categories ranked by impact, highest first"],
  "quick_wins": ["top 3 immediate changes with high impact-to-effort ratio"],
  "overall_diagnosis": "one paragraph system-level verdict"
}}"""

    log.info("Requesting system diagnosis from OpenAI (%d prompts) …", len(prompt_results))
    return await call_openai(
        client,
        api_key,
        system_msg=(
            "You are a software architect and music systems expert. "
            "Diagnose systemic failures in a playlist generation pipeline. "
            "Return only valid JSON."
        ),
        user_msg=user_msg,
        temperature=0.5,
    )


def write_system_report(
    run_dir: Path,
    prompt_results: dict[str, dict],
    aggregated: dict,
    diagnosis: dict,
) -> None:
    """Write a cross-prompt system diagnostic Markdown report."""
    lines: list[str] = []
    lines.append(f"# System Diagnostic Report — {run_dir.name}\n")
    lines.append(f"**Prompts evaluated:** {len(prompt_results)}\n")
    means = aggregated["means"]
    lines.append(f"**Aggregate weighted score:** {means['overall']:.2f}/10\n")
    lines.append("")

    lines.append("## Aggregate Scores\n")
    lines.append("| Dimension | Mean Score |")
    lines.append("|-----------|-----------|")
    for dim, label in [
        ("arc", "Arc Coherence"),
        ("genre", "Genre Accuracy"),
        ("transition", "Transition Quality"),
        ("fidelity", "Prompt Fidelity"),
        ("curation", "Curation Quality"),
        ("overall", "**Overall Weighted**"),
    ]:
        lines.append(f"| {label} | {means[dim]:.2f}/10 |")
    lines.append("")

    lines.append("## Per-Prompt Results\n")
    lines.append("| Prompt | Weighted | Arc | Genre | Trans | Fidelity | Curation |")
    lines.append("|--------|----------|-----|-------|-------|----------|----------|")
    for name, data in prompt_results.items():
        s = data.get("scores", {})
        lines.append(
            f"| {name} | **{data.get('weighted_score', 0):.2f}** "
            f"| {s.get('arc_coherence', '-')} | {s.get('genre_accuracy', '-')} "
            f"| {s.get('transition_quality', '-')} | {s.get('prompt_fidelity', '-')} "
            f"| {s.get('curation_quality', '-')} |"
        )
    lines.append("")

    issues = diagnosis.get("systemic_issues", [])
    if issues:
        lines.append("## Systemic Issues\n")
        for issue in issues:
            sev = issue.get("severity", "?")
            cat = issue.get("category", "?")
            lines.append(f"### [{sev}] {cat}\n")
            lines.append(f"{issue.get('description', '')}\n")
            evidence = issue.get("evidence", [])
            if evidence:
                lines.append("**Evidence:**")
                for e in evidence:
                    lines.append(f"- {e}")
                lines.append("")
            fix = issue.get("proposed_fix", {})
            if fix:
                lines.append(f"**Fix:** {fix.get('description', '')}\n")
                diff_text = fix.get("diff", "")
                if diff_text:
                    lines.append(f"```diff\n{diff_text}\n```\n")
                lines.append(f"**Expected impact:** {fix.get('expected_impact', '')}\n")

    quick_wins = diagnosis.get("quick_wins", [])
    if quick_wins:
        lines.append("## Quick Wins\n")
        for qw in quick_wins:
            lines.append(f"- {qw}")
        lines.append("")

    overall = diagnosis.get("overall_diagnosis", "")
    if overall:
        lines.append("## Overall Diagnosis\n")
        lines.append(f"> {overall}\n")

    report_path = run_dir / "system_report.md"
    report_path.write_text("\n".join(lines))
    log.info("System report written to %s", report_path)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run(
    prompt: str,
    threshold: float,
    max_iter: int,
    dry_run: bool,
    backend_url: str,
    api_key: str,
) -> tuple[int, list[dict]]:
    """Execute the full eval loop. Returns (exit_code, iterations)."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = EVAL_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info("Run ID: %s  →  %s", run_id, run_dir)

    iterations: list[dict] = []
    previous_prompts: list[str] = []
    current_prompt = prompt

    async with httpx.AsyncClient() as client:
        # Quick health check
        try:
            health = await client.get(
                f"{backend_url}/health",
                timeout=httpx.Timeout(5.0),
            )
            if health.status_code != 200:
                log.error("Backend health check failed: HTTP %s", health.status_code)
                return 1, []
            log.info("Backend is healthy")
        except httpx.ConnectError:
            log.error("Cannot reach backend at %s — is it running?", backend_url)
            return 1, []

        for iteration in range(1, max_iter + 1):
            log.info("━" * 50)
            log.info("ITERATION %d / %d", iteration, max_iter)
            log.info("━" * 50)

            # --- Step 1: Generate playlist ---
            try:
                playlist = await generate_playlist(client, backend_url, current_prompt)
            except Exception as e:
                log.error("Playlist generation failed: %s", e)
                return 1, []

            iter_prefix = f"iteration_{iteration}"
            response_path = run_dir / f"{iter_prefix}_response.json"
            response_path.write_text(json.dumps(playlist, indent=2, default=str))
            log.info("Saved response → %s", response_path.name)

            # --- Step 2: Evaluate ---
            try:
                evaluation = await evaluate_playlist(
                    client, api_key, prompt, playlist,
                )
            except json.JSONDecodeError as e:
                log.error("OpenAI returned malformed JSON: %s", e)
                return 1, []
            except Exception as e:
                log.error("Evaluation failed: %s", e)
                return 1, []

            eval_path = run_dir / f"{iter_prefix}_evaluation.json"
            eval_path.write_text(json.dumps(evaluation, indent=2, default=str))
            log.info("Saved evaluation → %s", eval_path.name)

            weighted = evaluation["weighted_score"]
            scores = evaluation.get("scores", {})

            iterations.append({
                "iteration": iteration,
                "prompt": current_prompt,
                "playlist": playlist,
                "evaluation": evaluation,
                "scores": scores,
                "weighted_score": weighted,
            })
            previous_prompts.append(current_prompt)

            # --- Step 3: Check threshold ---
            if weighted >= threshold:
                log.info("Score %.2f >= threshold %.1f — PASSING!", weighted, threshold)
                break

            if dry_run:
                log.info("Dry run — stopping after first evaluation")
                break

            if iteration == max_iter:
                log.info("Reached max iterations (%d) — stopping", max_iter)
                break

            # --- Step 4: Refine prompt ---
            try:
                strategy = await generate_refinement(
                    client, api_key,
                    original_prompt=prompt,
                    current_prompt=current_prompt,
                    evaluation=evaluation,
                    previous_prompts=previous_prompts,
                    iteration=iteration,
                )
            except json.JSONDecodeError as e:
                log.error("OpenAI refinement returned malformed JSON: %s", e)
                return 1, []
            except Exception as e:
                log.error("Refinement failed: %s", e)
                return 1, []

            strategy_path = run_dir / f"{iter_prefix}_strategy.json"
            strategy_path.write_text(json.dumps(strategy, indent=2, default=str))
            log.info("Saved strategy → %s", strategy_path.name)

            revised = strategy.get("revised_prompt", "")
            if not revised:
                log.error("Refinement produced no revised_prompt — aborting")
                return 1, []

            changes = strategy.get("changes_made", [])
            log.info("Refinement reasoning: %s", strategy.get("reasoning", "?")[:200])
            for c in changes:
                log.info("  • %s", c)

            # Guard against prompt over-specification: if the refined prompt
            # is >2x the original length, it's probably over-engineered.
            if len(revised) > len(prompt) * 2.5:
                log.warning(
                    "Refined prompt is %.0f%% longer than original — trimming",
                    len(revised) / len(prompt) * 100,
                )
                # Fall back to original with just the top change appended
                top_change = changes[0] if changes else ""
                revised = prompt + f" Additionally: {top_change}" if top_change else prompt

            current_prompt = revised

    # --- Final report ---
    write_report(run_dir, iterations, prompt)
    print_summary(iterations, threshold)
    return 0, iterations


# ---------------------------------------------------------------------------
# Multi-prompt batch loop
# ---------------------------------------------------------------------------


async def run_multi(
    prompts: list[tuple[str, str]],
    threshold: float,
    max_iter: int,
    dry_run: bool,
    backend_url: str,
    api_key: str,
) -> int:
    """Batch-evaluate all prompts, aggregate results, then diagnose systemic issues."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_multi"
    run_dir = EVAL_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info("Multi-prompt run: %s  →  %s", run_id, run_dir)

    prompt_results: dict[str, dict] = {}
    exit_codes: list[int] = []

    for name, prompt_text in prompts:
        log.info("\n" + "=" * 60)
        log.info("BATCH [%d/%d]: %s", len(exit_codes) + 1, len(prompts), name)
        log.info("=" * 60)
        code, iterations = await run(
            prompt=prompt_text,
            threshold=threshold,
            max_iter=max_iter,
            dry_run=dry_run,
            backend_url=backend_url,
            api_key=api_key,
        )
        exit_codes.append(code)
        if iterations:
            best = max(iterations, key=lambda it: it["weighted_score"])
            prompt_results[name] = {
                "scores": best["scores"],
                "weighted_score": best["weighted_score"],
                "evaluation": best.get("evaluation", {}),
                "prompt": prompt_text,
                "playlist_title": best.get("playlist", {}).get("title", "?"),
            }

    if not prompt_results:
        log.error("No successful runs — skipping aggregation")
        return max(exit_codes) if exit_codes else 1

    # --- Aggregate ---
    aggregated = aggregate_results(prompt_results)
    means = aggregated["means"]

    print("\n" + "=" * 60)
    print("  BATCH RESULTS")
    print("=" * 60)
    for name, data in prompt_results.items():
        print(f"  {name:30s} {data['weighted_score']:.2f}  '{data.get('playlist_title', '?')}'")
    print(
        f"\n  Aggregate: arc={means['arc']:.1f}  genre={means['genre']:.1f}  "
        f"transition={means['transition']:.1f}  fidelity={means['fidelity']:.1f}  "
        f"curation={means['curation']:.1f}  → overall={means['overall']:.2f}"
    )
    print("=" * 60)

    agg_path = run_dir / "aggregated.json"
    agg_path.write_text(
        json.dumps({"aggregated": aggregated, "prompt_results": prompt_results}, indent=2, default=str)
    )
    log.info("Saved aggregated results → %s", agg_path.name)

    # --- System diagnosis ---
    async with httpx.AsyncClient() as client:
        try:
            diagnosis = await diagnose_system(client, api_key, prompt_results, aggregated)
            diagnosis_path = run_dir / "diagnosis.json"
            diagnosis_path.write_text(json.dumps(diagnosis, indent=2, default=str))
            log.info("Saved diagnosis → %s", diagnosis_path.name)

            write_system_report(run_dir, prompt_results, aggregated, diagnosis)

            print("\n" + "=" * 60)
            print("  SYSTEM DIAGNOSIS")
            print("=" * 60)
            for issue in diagnosis.get("systemic_issues", []):
                desc = issue.get("description", "")[:80]
                print(f"  [{issue.get('severity', '?')}] {issue.get('category', '?')}: {desc}")
            quick_wins = diagnosis.get("quick_wins", [])
            if quick_wins:
                print("\n  Quick wins:")
                for qw in quick_wins[:3]:
                    print(f"    • {qw[:100]}")
            print(f"\n  Full report: {run_dir / 'system_report.md'}")
            print("=" * 60)
        except Exception as exc:
            log.error("System diagnosis failed: %s", exc)

    return max(exit_codes) if exit_codes else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated Prompt Evaluation & Tuning Loop for Playlist Generator",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=DEFAULT_PROMPT,
        help="Custom prompt to evaluate (default: built-in ambient→doom arc prompt)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Weighted score threshold to pass (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=DEFAULT_MAX_ITER,
        help=f"Maximum iterations (default: {DEFAULT_MAX_ITER})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run Steps 1–2 once and print the evaluation without looping",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Batch-evaluate all diverse prompts, aggregate, then diagnose systemic issues",
    )
    args = parser.parse_args()

    load_env()
    api_key = require_env("OPENAI_API_KEY")
    backend_url = os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL)

    if args.multi:
        exit_code = asyncio.run(
            run_multi(
                prompts=MULTI_PROMPTS,
                threshold=args.threshold,
                max_iter=args.max_iter,
                dry_run=args.dry_run,
                backend_url=backend_url,
                api_key=api_key,
            )
        )
        sys.exit(exit_code)
    else:
        exit_code, _ = asyncio.run(
            run(
                prompt=args.prompt,
                threshold=args.threshold,
                max_iter=args.max_iter,
                dry_run=args.dry_run,
                backend_url=backend_url,
                api_key=api_key,
            )
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
