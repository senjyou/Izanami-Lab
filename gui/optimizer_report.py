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
    label = "当日最高" if objective == obj.OBJECTIVE_ROLL5 else "均值"
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


def format_report(result, resolver=None):
    """The run summary as text, with no ids and no table.

    The lineup itself is NOT repeated here: ``gui.optimizer_preview`` draws the
    same candidates as real card thumbnails directly under the panel, and card art
    identifies a character far better than a name. So the text carries what a
    picture cannot -- the numbers, the ranking and the comparison -- and stays
    compact enough to read without scrolling.

    ``resolver`` is accepted for callers that still want names in the text, but is
    only used to label anything the preview cannot show.
    """
    settings = result.get("settings") or {}
    objective = result.get("objective", obj.OBJECTIVE_MEAN)
    label = "当日最高 Roll5" if objective == obj.OBJECTIVE_ROLL5 else "均值"
    space = result.get("space") or {}

    lines = [
        f"【智能优化 · {label}】",
        f"预算 {settings.get('budget', 0):,} 场　实际 "
        f"{result.get('battles', 0):,} 场　{result.get('elapsed', 0):.1f} 秒　"
        f"{result.get('workers', '?')} 进程",
        f"空间 {space.get('positions', '?')} 站位 × "
        f"{space.get('memories', '?')} 回忆 = {space.get('combined', 0):,}",
        f"结果：{result.get('termination')}",
    ]
    detail = result.get("detail", "")
    if detail:
        lines.extend(_wrap_plain(detail, indent="  "))
    lines.append("")

    best = result.get("best_summary")
    baseline = result.get("baseline_summary")

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

    candidates = result.get("candidates") or []
    if not candidates:
        lines.append("没有候选完成完整的精评种子组。")
        lines.append("可提高预算，或缩小回忆卡池后重试。")
        return "\n".join(lines) + "\n"

    shown = candidates[:LEADERBOARD_LIMIT]
    ranks = [c.get("summary", {}).get("rank", 0.0) for c in shown]
    top, bottom = max(ranks), min(ranks)
    lines.append(f"═══ 候选排行（前 {len(shown)} / 共 {len(candidates)}）═══")
    lines.append("")
    for cand in shown:
        lines.extend(format_candidate_block(cand, top, bottom, resolver,
                                            objective))
    limited = min(len(candidates), PREVIEW_LIMIT)
    pages = (limited + 2) // 3
    lines.append(f"（前 {limited} 名的阵容见图，共 {pages} 页，可翻页查看）")
    lines.append("")
    lines.extend(_wrap_plain("提示：点击「应用最优站位」可写回当前页面。"))
    return "\n".join(lines) + "\n"
