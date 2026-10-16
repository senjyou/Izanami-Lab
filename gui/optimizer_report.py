# -*- coding: utf-8 -*-
"""Presentation of an optimizer result: names only, and no tables.

Two rules shape this module.

**No identifiers.** Character and memory ids are unpacked game data, not
something a player of this game reads. Every id that reaches the screen is
resolved to its display name; when a name cannot be resolved the label says so
rather than falling back to the raw number, because printing the number is
exactly the leak this module exists to prevent.

**No table.** A ranked result is presented as a vertical leaderboard with a
proportional bar, in the result panel's own text area. A grid of columns forced
the reader to scan sideways across a scrollbar to compare two candidates, and it
also made the ids look like the payload. A bar makes the ranking readable at a
glance, and each entry can carry its full lineup underneath in prose.
"""

from src.optimizer import objective as obj

# How many candidates the leaderboard lists. Beyond this the differences are
# inside the measurement noise and the list stops being readable.
LEADERBOARD_LIMIT = 10

# How many candidates the thumbnail strip can show in total, across its pages.
# Kept in step with gui.optimizer_preview's PAGE_SIZE * MAX_PAGES so the text and
# the pictures agree about how far the preview reaches.
PREVIEW_LIMIT = 30

# The result panel's text area is a fixed-width widget (about 50 columns), and
# these names are CJK -- two columns per glyph -- so hard-wrapping is the norm.
# Lines are wrapped here, by DISPLAY width, rather than left to the widget: a
# naive wrap cuts mid-name and puts a stray fragment on the next line, which is
# what made the first version of this report unreadable.
PANEL_COLUMNS = 48


def _display_width(text):
    """Columns a string occupies, counting wide (CJK) glyphs as two."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def _wrap_entries(entries, indent, columns=PANEL_COLUMNS, separator="　"):
    """Join entries onto lines no wider than ``columns`` display columns.

    Each entry is kept whole: an entry that does not fit starts a new line rather
    than being split, so a name never appears broken across two lines.
    """
    if not entries:
        return []
    lines = []
    current = ""
    for entry in entries:
        candidate = entry if not current else current + separator + entry
        if current and _display_width(indent + candidate) > columns:
            lines.append(indent + current)
            current = entry
        else:
            current = candidate
    if current:
        lines.append(indent + current)
    return lines


class NameResolver:
    """Resolve ids to display names, never back to the id.

    Caches lookups because a leaderboard resolves the same few characters and
    cards repeatedly.
    """

    def __init__(self, data_loader=None):
        self._loader = data_loader
        self._chars = {}
        self._memories = {}

    def character(self, cid):
        """Display name for a character id, or a generic label."""
        if cid is None:
            return "空位"
        if cid not in self._chars:
            self._chars[cid] = self._lookup_char(cid)
        return self._chars[cid]

    def memory(self, mid):
        """Display name for a memory id, or a generic label."""
        if mid is None:
            return "（未选）"
        if mid not in self._memories:
            self._memories[mid] = self._lookup_memory(mid)
        return self._memories[mid]

    def _lookup_char(self, cid):
        if self._loader is None:
            return "未知角色"
        try:
            character = self._loader.get_character_by_id(cid)
        except Exception:
            character = None
        name = getattr(character, "name", None) if character else None
        return name or "未知角色"

    def _lookup_memory(self, mid):
        if self._loader is None:
            return "未知回忆"
        try:
            memory = self._loader.get_memory(mid)
        except Exception:
            memory = None
        name = getattr(memory, "name", None) if memory else None
        return name or "未知回忆"


def _wrap_plain(text, indent=""):
    """Wrap arbitrary prose to the panel width, breaking only at spaces.

    Used for the run's free-text detail line, which the search composes itself and
    which can therefore be longer than the panel is wide.
    """
    if not text:
        return []
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and _display_width(indent + candidate) > PANEL_COLUMNS:
            lines.append(indent + current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(indent + current)
    return lines


def format_candidate_block(cand, best_rank, worst_rank, resolver,
                           objective, show_detail=False):
    """One leaderboard entry: rank and score.

    No bar. A proportional bar was tried and removed: at the panel's width it
    pushed the score onto a second line, and with ten rows of near-identical
    lengths it added vertical noise without making the order any clearer than the
    rank number already does. The hierarchy that IS worth showing -- which lineup
    won -- is carried by the card thumbnails, not by glyph length.

    ``best_rank`` / ``worst_rank`` / ``resolver`` are kept in the signature so
    callers do not have to change, but the entry no longer needs them.
    """
    summary = cand.get("summary") or {}
    # The "current lineup" marker rides the spread line: on the score line it
    # pushes the row past the panel width and hard-wraps the score itself.
    baseline = "　【当前阵容】" if cand.get("is_baseline") else ""
    return [
        f"  #{cand.get('rank', '?'):<2} {_headline(summary, objective)}",
        f"       {_compact_spread(summary)}{baseline}",
    ]


def _compact_spread(summary):
    """Spread and sample count, abbreviated to fit a ranking row.

    The full form (``σ 8,132,029　CV 7.2%　8 场``) is used for the champion, where
    there is room on its own line. A ranking row uses the short one so the entry
    stays inside the panel width instead of wrapping.
    """
    sd = summary.get("sd")
    cv = summary.get("cv")
    parts = []
    if isinstance(sd, (int, float)):
        parts.append(f"σ{sd / 10000:.0f}万" if abs(sd) >= 10000 else f"σ{sd:,.0f}")
    if isinstance(cv, (int, float)):
        parts.append(f"CV{cv:.1f}%")
    return "\u00a0".join(parts)


def _score_text(summary, objective):
    """The one number that decided this ranking, plus its spread."""
    return f"{_headline(summary, objective)}　{_spread_text(summary)}"


def _headline(summary, objective):
    """The ranking number alone, for a leaderboard row.

    The label and its number are joined by a non-breaking space so the wrapper
    never separates them.
    """
    label = {"roll5": "当日最高", "floor": "保底"}.get(objective, "均值")
    return f"{label}\u00a0{summary.get('rank', 0):,.0f}"


def _spread_text(summary):
    """Spread and sample count, as ONE unbreakable unit.

    Internal spaces are non-breaking (U+00A0), because the code that wraps prose
    breaks on the ASCII space: with an ordinary space, "CV 7.2%" split across
    lines as "CV" / "7.2%", which reads like two unrelated facts.
    """
    nb = "\u00a0"
    return (f"σ{nb}{summary.get('sd', 0):,.0f}　"
            f"CV{nb}{summary.get('cv', 0):.1f}%　"
            f"{summary.get('n', 0)}{nb}场")


def _coverage(result, total):
    """How much of the space was actually screened, parsed from the run detail.

    Returns ``(screened, percent)`` or None when the count cannot be read. The
    detail line is written by the search, so this keeps one source of truth.
    """
    detail = result.get("detail") or ""
    if "粗筛" not in detail or not total:
        return None
    try:
        text = detail.split("粗筛", 1)[1]
        screened = int(text.split("个", 1)[0].strip().replace(",", ""))
    except (IndexError, ValueError):
        return None
    return screened, screened / total * 100.0


def _candidate_states(result):
    """Ranked finalist states, best first, from the real V3.2 result.

    The ported engine's final shortlist lives in ``independent_validation.candidates``
    (each with a ``state`` and the final ``mean``), NOT in a ``joint`` or
    ``candidates`` key -- those are absent from the published result. This reads the
    shortlist and sorts it by ``mean`` descending. Returns [] when there is none.
    """
    iv = result.get("independent_validation") or {}
    cands = list(iv.get("candidates") or [])
    if not cands:
        return []
    def _key(c):
        m = c.get("mean")
        return float(m) if isinstance(m, (int, float)) else float("-inf")
    return sorted(cands, key=_key, reverse=True)


def _champion_scores(result):
    """Champion and baseline (score, spread) from the finalists + joint_seed_scores."""
    import statistics as _st
    finalists = _candidate_states(result)
    flat = result.get("joint_seed_scores") or []

    def _spread_for(key, seeds):
        seedset = set(seeds or [])
        scores = [float(r["score"]) for r in flat
                  if r.get("configuration_key") == key
                  and isinstance(r.get("score"), (int, float))
                  and (not seedset or r.get("seed") in seedset)]
        n = len(scores)
        if n < 2:
            return dict(sd=0.0, cv=0.0, n=n)
        sd = _st.stdev(scores)
        mean = _st.mean(scores)
        return dict(sd=sd, cv=(sd / mean * 100.0) if mean else 0.0, n=n)

    best = None
    if finalists:
        top = finalists[0]
        m = top.get("mean")
        if isinstance(m, (int, float)):
            best = dict(rank=float(m),
                        **_spread_for(top.get("configuration_key"), top.get("seeds")))
    # Baseline = the finalist matching the original lineup, else the lowest finalist.
    baseline = None
    orig = result.get("original") or {}
    okey = (tuple(orig.get("friend_positions") or ()),
            tuple(orig.get("memory_ids") or ()))
    base_row = None
    for c in finalists:
        st = c.get("state") or {}
        if (tuple(st.get("friend_positions") or ()),
                tuple(st.get("memory_ids") or ())) == okey:
            base_row = c
            break
    if base_row is None and finalists:
        base_row = finalists[-1]
    if base_row is not None:
        m = base_row.get("mean")
        if isinstance(m, (int, float)):
            baseline = dict(rank=float(m),
                            **_spread_for(base_row.get("configuration_key"),
                                          base_row.get("seeds")))
    return best, baseline


def _ranked_joint(result):
    """Finalist rows (value, {configuration_key, state, mean}) for the leaderboard."""
    out = []
    for c in _candidate_states(result):
        m = c.get("mean")
        if isinstance(m, (int, float)):
            out.append((float(m), c))
    return out


def format_report(result, resolver=None):
    """The run summary as text, with no ids and no table.

    Built for the ported V3.2 result format: the champion/baseline are the
    independent-validation scores, the space is the layered joint total, and the
    leaderboard is the layered review ranking.
    """
    settings = result.get("settings") or {}
    objective = settings.get("objective", obj.OBJECTIVE_MEAN)
    label = obj.OBJECTIVE_LABELS.get(objective, "均值")
    layered = result.get("layered") or {}
    simulations = result.get("simulations", 0)
    workers = settings.get("battle_workers", "?")
    if workers == 0:
        workers = "自动"

    lines = [
        f"【智能优化 · {label}】",
        f"预算 {settings.get('budget', 0):,} 场　实际 {simulations:,} 场",
        f"用时 {result.get('elapsed', 0):.1f} 秒　{workers} 进程",
    ]
    positions = layered.get("position_total")
    memories = layered.get("legal_memory_combinations")
    joint = layered.get("joint_total")
    if positions is not None:
        lines.append(f"空间 {positions} 站位 × {memories or '?'} 回忆"
                     + (f" = {joint:,}" if joint else ""))
    reason = result.get("termination_reason") or result.get("phase") or ""
    lines.append(f"结果：{reason}")
    detail = result.get("termination_detail") or ""
    if detail and detail not in reason:
        lines.extend(_wrap_plain(detail, indent="  "))
    stage = layered.get("stage")
    if stage and stage not in (reason, detail):
        lines.append(f"阶段：{stage}")
    lines.append("")

    best, baseline = _champion_scores(result)
    if best:
        lines.append("═══ 冠军 ═══")
        lines.append(f"  {_headline(best, objective)}")
        lines.append(f"     {_spread_text(best)}")
        lines.append("  阵容见下方缩略图")
        lines.append("")

    if best and baseline:
        lines.append("═══ 与当前阵容对比 ═══")
        lines.append(f"  当前　{_headline(baseline, objective)}")
        lines.append(f"        {_spread_text(baseline)}")
        delta = best["rank"] - baseline["rank"]
        pct = (delta / baseline["rank"] * 100) if baseline["rank"] else 0.0
        verdict = "提升" if delta >= 0 else "下降"
        lines.append(f"  {verdict} {delta:+,.0f}（{pct:+.2f}%）")
        lines.append("")

    joint_scored = _ranked_joint(result)
    if not joint_scored:
        lines.append("没有候选进入复评名单；可提高预算或缩小卡池。")
        lines.extend(_wrap_plain("提示：点击「应用最优站位」可写回当前页面。", indent=""))
        return "\n".join(lines) + "\n"

    shown = joint_scored[:LEADERBOARD_LIMIT]
    values = [v for v, _ in shown]
    top, bottom = (max(values), min(values)) if values else (0, 0)
    lines.append(f"═══ 候选排行（前 {len(shown)} / 共 {len(joint_scored)}）═══")
    lines.append("")
    for rank, (value, cand) in enumerate(shown, start=1):
        state = cand.get("state") or {}
        n = cand.get("seed_count") or 0
        # is_baseline: the candidate whose lineup equals the original (current) page.
        orig = result.get("original") or {}
        is_base = (tuple(state.get("friend_positions") or ())
                   == tuple(orig.get("friend_positions") or ())
                   and tuple(state.get("memory_ids") or ())
                   == tuple(orig.get("memory_ids") or ()))
        summary = {"rank": value, "n": n}
        # Real spread for this finalist, from its joint_seed_scores.
        import statistics as _st
        flat = result.get("joint_seed_scores") or []
        seedset = set(cand.get("seeds") or [])
        sscores = [float(r["score"]) for r in flat
                   if r.get("configuration_key") == cand.get("configuration_key")
                   and isinstance(r.get("score"), (int, float))
                   and (not seedset or r.get("seed") in seedset)]
        if len(sscores) > 1:
            sd = _st.stdev(sscores)
            mn = _st.mean(sscores)
            summary.update(sd=sd, cv=(sd / mn * 100.0) if mn else 0.0)
        lines.extend(format_candidate_block(
            {"rank": rank, "is_baseline": is_base, "summary": summary},
            top, bottom, resolver, objective))
    lines.append("")
    lines.extend(_wrap_plain("提示：点击「应用最优站位」可写回当前页面。"))
    return "\n".join(lines) + "\n"
