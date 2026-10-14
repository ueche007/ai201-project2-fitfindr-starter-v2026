#!/usr/bin/env python3
"""
Apply criteria.md to a run and print the run log. ← UNIT 4, MILESTONES 3 & 4

    python score.py results/run_2026-10-13_1420_before.json
    python score.py --latest before

run_eval.py runs the scenarios and deliberately leaves the PASS/FAIL columns
blank, because deciding what counts as a pass is the lesson. This file is that
decision, written down.

Why in code rather than by eye. The scenario set is 45 runs per label. Marking
those by hand is not a test of the agent, it is a test of whether I still
remember on row 40 what I decided on row 3 — and the one direction that drift
reliably runs in is the direction that makes the agent look better. Every
clause of every criterion below is quoted from criteria.md in the docstring
next to the code that checks it, so the mapping can be audited and disagreed
with. Nothing here decides anything criteria.md did not already say; where a
clause needed interpreting to be executable, the interpretation is called out
in the docstring as INTERPRETATION and repeated in the README.

A "try" is one repetition of a criterion's whole scenario set. See the header
of scenarios.py for why.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import config

# ── Reading what the model wrote ──────────────────────────────────────────────

# Title words too generic to prove a card is talking about the right item.
# "Vintage Band Tee" and "Vintage Linen Blazer" share "vintage", so "vintage"
# cannot be the word that identifies either of them.
_GENERIC_TITLE_WORDS = {
    "vintage", "style", "print", "wash", "faded", "oversized", "light",
    "medium", "dark", "reversible", "adjustable", "size", "and", "the",
}

_CATEGORY_WORDS = {
    "tops": ("top", "tee", "shirt", "sweatshirt", "crewneck", "hoodie",
             "cardigan", "blouse", "knit"),
    "bottoms": ("bottom", "pants", "trousers", "jeans", "shorts", "skirt",
                "denim"),
    "outerwear": ("jacket", "coat", "blazer", "bomber", "windbreaker",
                  "shacket", "vest", "outerwear"),
    "shoes": ("shoe", "sneaker", "boot", "mary jane", "loafer", "trainer"),
    "accessories": ("belt", "hat", "bag", "purse", "accessory", "accessories"),
}


def _title_tokens(title: str) -> set[str]:
    """
    The words in a title that could identify the item in a caption.

    Four letters or more, minus the generic set. "Platform Mary Janes — Black
    Patent" gives {"platform", "mary", "janes", "black", "patent"} — "mary" and
    "janes" are three and five letters, so the length floor is 3 here, not 4.
    """
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _GENERIC_TITLE_WORDS}


def _word_in(token: str, text: str) -> bool:
    """
    True when `token` appears in `text` as a word, singular or plural.

    Whole-word and not substring, which was a real bug in the first version of
    this file: "hat" is inside "that", so every caption containing the word
    "that" counted as naming a bucket hat. Substring matching is right in
    tools.py, where "tee" should find "Baby Tee", and wrong here, where the
    question is whether a caption is talking about a particular listing.
    """
    return re.search(r"\b" + re.escape(token) + r"s?\b", text or "") is not None


def _mentions_item(text: str, item: dict) -> bool:
    """True when `text` names the item: any distinctive word from its title."""
    low = (text or "").lower()
    return any(_word_in(t, low) for t in _title_tokens(item.get("title", "")))


def _identifying_hits(card: str, results: list[dict]) -> dict[str, list[str]]:
    """
    For each search result, which of its title words — words belonging to it
    and to no other candidate in the same result set — the card actually uses.

    This is how criterion 3's last clause gets checked. See check_3 for why it
    is done by comparing candidates rather than by looking at the selected item
    alone.
    """
    tokens = {r.get("id"): _title_tokens(r.get("title", "")) for r in results}
    seen = Counter(t for ts in tokens.values() for t in ts)
    low = (card or "").lower()
    return {
        rid: sorted(t for t in ts if seen[t] == 1 and _word_in(t, low))
        for rid, ts in tokens.items()
    }


def _mentions_item_or_category(text: str, item: dict) -> bool:
    """
    Criterion 4: "names the item or its category".

    INTERPRETATION. The literal category strings in the data are "tops",
    "bottoms", "outerwear", "shoes" and "accessories", and no caption written
    by a person would contain the word "tops". So "its category" is read as the
    kind of garment it is — the words in _CATEGORY_WORDS for that category —
    rather than the data's bucket name. This is more generous than the literal
    reading and it is the reading I would defend: a card opening "this cropped
    denim jacket" has named the category of an outerwear listing.
    """
    if _mentions_item(text, item):
        return True
    low = (text or "").lower()
    return any(
        _word_in(word, low) if " " not in word else word in low
        for word in _CATEGORY_WORDS.get(item.get("category"), ())
    )


def _sentences(card: str) -> list[str]:
    """
    Split a caption into sentences.

    Decimal points and "U.S." are the usual traps; prices in this data are
    whole dollars and the cards are two to four sentences of plain prose, so a
    split on .!? followed by whitespace-or-end is accurate enough. Emoji and
    newlines are treated as ordinary characters, not terminators.
    """
    text = (card or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])(?=\s|$)", text)
    return [p.strip() for p in parts if p.strip()]


def _states_price(card: str, price) -> bool:
    """
    Criterion 4: the card "contains the item's price as a number".

    Matches the price written as a person writes it — 19, 19.0, 19.00 — and
    refuses a match that is part of a longer number, so a card mentioning
    "1990s" does not count as stating a $19 price.
    """
    try:
        value = float(price)
    except (TypeError, ValueError):
        return False
    whole = f"{value:.0f}"
    forms = {whole, f"{value:.1f}", f"{value:.2f}"}
    if value >= 1000:
        forms.add(f"{value:,.0f}")
    return any(
        re.search(r"(?<![\d.,])" + re.escape(f) + r"(?![\d])", card or "")
        for f in forms
    )


def _names_platform(card: str, platform: str) -> bool:
    """
    Criterion 4: the card contains "its platform name".

    Case-insensitive, and whitespace is squashed on both sides first so that
    "Thred Up" counts as naming thredUp. A card that gets the platform's
    capitalisation wrong has still told the user where to buy it, which is what
    the criterion is protecting.
    """
    if not platform:
        return False
    squash = lambda s: re.sub(r"\s+", "", (s or "").lower())
    return squash(platform) in squash(card)


# ── Reading the trace ─────────────────────────────────────────────────────────

def _trace_steps(trace_text: str) -> list[dict]:
    """
    Parse a trace back into steps.

    trace.py writes "[n] name" and then indented "in:", "out:" and "→" lines,
    which is regular enough to read back. Criterion 3 specifies that it is
    checked by reading the trace, so the trace is what is read — not the
    session that produced it. Checking the session against itself would pass a
    loop that wrote the same wrong item to both places, which is the bug
    criterion 3 says it exists to catch.
    """
    steps = []
    current = None
    for line in (trace_text or "").splitlines():
        head = re.match(r"\[(\d+)\]\s+(.*)$", line)
        if head:
            current = {"n": int(head.group(1)), "name": head.group(2).strip(),
                       "in": "", "out": "", "note": ""}
            steps.append(current)
            continue
        if current is None:
            continue
        for marker, key in (("in:", "in"), ("out:", "out"), ("→", "note")):
            if line.strip().startswith(marker):
                current[key] += line.strip()[len(marker):].strip()
    return steps


def _step_named(steps, name) -> dict | None:
    for s in steps:
        if s["name"].startswith(name):
            return s
    return None


def _id_in(text: str) -> str | None:
    found = re.findall(r"lst_\d+", text or "")
    return found[0] if found else None


# ── The five criteria ─────────────────────────────────────────────────────────
#
# Each checker takes one run and returns (passed, reason). `reason` is only
# read when it failed — it is what the diagnosis is written from, so it names
# the step and the mechanism rather than saying "wrong".


def check_1(run) -> tuple[bool, str]:
    """
    Criterion 1: "the agent completes all three tool calls and returns a fit
    card". Target 4 of 5.

    All three means the three tools of the original inventory —
    search_listings, suggest_outfit, create_fit_card. compare_prices is the
    fourth, stretch tool and criterion 1 predates it.
    """
    if run["crashed"]:
        return False, f"crashed: {run['crashed']}"
    s = run["session"] or {}
    if s.get("error"):
        return False, f"ended early with an error: {str(s['error'])[:120]}"
    if not s.get("search_results"):
        return False, "search_results was empty — routed to the empty branch"
    steps = _trace_steps(run["trace"])
    for tool in ("search_listings", "suggest_outfit", "create_fit_card"):
        if not _step_named(steps, tool):
            return False, f"no {tool} step in the trace — the tool was not called"
    if not (s.get("outfit_suggestion") or "").strip():
        return False, "suggest_outfit returned nothing"
    card = (s.get("fit_card") or "").strip()
    if not card:
        return False, "create_fit_card returned nothing"
    if card.startswith("No fit card"):
        return False, f"create_fit_card returned its own empty-case string: {card}"
    return True, ""


def check_2(run) -> tuple[bool, str]:
    """
    Criterion 2: "the agent stops before calling suggest_outfit and returns a
    message naming what to change". Target 5 of 5.
    """
    if run["crashed"]:
        return False, f"crashed: {run['crashed']}"
    s = run["session"] or {}
    if s.get("search_results"):
        return False, (
            f"search returned {len(s['search_results'])} results, so this "
            f"query was not actually impossible — the scenario is wrong, not "
            f"the branch"
        )
    steps = _trace_steps(run["trace"])
    if _step_named(steps, "suggest_outfit"):
        return False, "suggest_outfit appears in the trace — the branch did not stop"
    if s.get("outfit_suggestion") is not None:
        return False, "session['outfit_suggestion'] was set past the branch"
    if s.get("fit_card") is not None:
        return False, "session['fit_card'] was set past the branch"
    message = s.get("error") or ""
    if not message.strip():
        return False, "stopped, but session['error'] was empty — no message at all"
    if "To get results" not in message:
        return False, (
            "the message does not say what to change — criterion 2 asks for a "
            "message naming what to change, not just that nothing was found"
        )
    return True, ""


def check_3(run) -> tuple[bool, str]:
    """
    Criterion 3: the selected id on the select_item step, the id on the
    suggest_outfit step and an id in search_results must all be the same
    string, "and the fit card's named item must be that listing's title".
    Target 5 of 5. Read from the trace, as the criterion specifies.
    """
    if run["crashed"]:
        return False, f"crashed: {run['crashed']}"
    s = run["session"] or {}
    if s.get("error"):
        return False, f"ended early, so there is no identity to check: {str(s['error'])[:90]}"

    steps = _trace_steps(run["trace"])
    select = _step_named(steps, "select_item")
    suggest = _step_named(steps, "suggest_outfit")
    if not select:
        return False, "no select_item step in the trace"
    if not suggest:
        return False, "no suggest_outfit step in the trace"

    id_select = _id_in(select["note"]) or _id_in(select["out"])
    id_suggest = _id_in(suggest["in"])
    if not id_select:
        return False, "the select_item step records no listing id"
    if not id_suggest:
        return False, "the suggest_outfit step records no listing id"
    if id_select != id_suggest:
        return False, (
            f"the loop selected {id_select} but passed {id_suggest} into "
            f"suggest_outfit — the session and the call disagree"
        )

    result_ids = [r.get("id") for r in (s.get("search_results") or [])]
    if id_select not in result_ids:
        return False, (
            f"{id_select} was styled but is not in search_results "
            f"({', '.join(result_ids[:4])}…) — the loop wrote an item the "
            f"search never returned"
        )
    session_id = ((s.get("selected_item") or {}).get("id"))
    if session_id != id_select:
        return False, (
            f"the trace says {id_select}, session['selected_item']['id'] says "
            f"{session_id}"
        )

    # ── "and the fit card's named item must be that listing's title" ──────
    #
    # INTERPRETATION, and it decides a verdict, so it is argued rather than
    # asserted. Read literally — the card contains the title verbatim — this
    # clause fails almost every card ever written, because "Vintage Band Tee —
    # Faded Grey" is a listing title and not a sentence. Read loosely — the
    # card shares any word with the title — it passes a card that is plainly
    # describing a different listing, because "tee" is shared by three of the
    # candidates in one of these result sets.
    #
    # So it is read for what criteria.md says the clause is FOR: "an off-by-one
    # there would style candidate n while having written candidate n+1 into the
    # session ... nothing in the user-facing output would look wrong". The
    # question that answers is not "does the card mention this item" but "of
    # the candidates the search returned, which one is this card describing".
    # The card must use at least one word belonging to the selected listing and
    # to no other candidate, and must not fit a rival candidate better.
    #
    # This is the strict reading of the three. It is also the only one of the
    # three that can detect the bug the criterion says it exists to detect,
    # which is why it is the one used. Both numbers are reported in the README.
    item = s.get("selected_item") or {}
    card = s.get("fit_card") or ""
    results = s.get("search_results") or []
    hits = _identifying_hits(card, results)
    mine = hits.get(id_select, [])
    rivals = {rid: words for rid, words in hits.items() if rid != id_select and words}
    best_rival = max((len(w) for w in rivals.values()), default=0)

    if not mine or len(mine) < best_rival:
        titles = {r.get("id"): r.get("title") for r in results}
        if rivals:
            worst = max(rivals, key=lambda r: len(rivals[r]))
            return False, (
                f"the card uses no word that identifies the selected "
                f"{id_select} ({item.get('title')!r}) among the search "
                f"results, but does use {rivals[worst]} — words belonging to "
                f"{worst} ({titles.get(worst)!r}), a different candidate in "
                f"the same result set. The ids above all agree, so the loop "
                f"did not mix the items up; the caption did"
            )
        return False, (
            f"the card uses no word that identifies the selected {id_select} "
            f"({item.get('title')!r}) among the search results, so it cannot "
            f"be shown to be about that listing rather than a neighbour"
        )
    return True, ""


def check_4_card(run) -> tuple[bool, str]:
    """
    Criterion 4, the per-card half: every card "contains the item's price as a
    number and its platform name, and names the item or its category in the
    first sentence", and "each card must be between 2 and 4 sentences and
    under 400 characters". Target 5 of 5.
    """
    if run["crashed"]:
        return False, f"crashed: {run['crashed']}"
    s = run["session"] or {}
    if s.get("error"):
        return False, f"no card was written: {str(s['error'])[:90]}"
    card = (s.get("fit_card") or "").strip()
    item = s.get("selected_item") or {}
    if not card:
        return False, "no fit card"

    faults = []
    if not _states_price(card, item.get("price")):
        faults.append(f"price ${item.get('price')} not stated as a number")
    if not _names_platform(card, item.get("platform")):
        faults.append(f"platform {item.get('platform')!r} not named")

    sents = _sentences(card)
    if not sents:
        faults.append("no sentences")
    elif not _mentions_item_or_category(sents[0], item):
        faults.append(
            f"first sentence names neither the item nor its category "
            f"({sents[0][:90]!r})"
        )
    if not (2 <= len(sents) <= 4):
        faults.append(f"{len(sents)} sentences, outside 2–4")
    if len(card) >= 400:
        faults.append(f"{len(card)} characters, not under 400")

    return (not faults), "; ".join(faults)


def check_5a(run) -> tuple[bool, str]:
    """
    Criterion 5(a): "no listing in session['search_results'] has a price above
    that ceiling — zero violations in total across all results returned, not
    just the selected one". Target 5 of 5.
    """
    if run["crashed"]:
        return False, f"crashed: {run['crashed']}"
    s = run["session"] or {}
    ceiling = (s.get("parsed") or {}).get("max_price")
    if ceiling is None:
        return False, (
            "the parser found no price ceiling in a query that names one — "
            "max_price came back None, so the search ran with no ceiling at all"
        )
    over = [
        f"{r.get('id')} at ${r.get('price')}"
        for r in (s.get("search_results") or [])
        if r.get("price") is None or float(r["price"]) > float(ceiling)
    ]
    if over:
        return False, (
            f"{len(over)} result(s) above the ${ceiling:g} ceiling: "
            f"{', '.join(over)}"
        )
    return True, ""


def check_5b(run) -> tuple[bool, str]:
    """
    Criterion 5(b): the message "names at least one specific constraint from
    the parsed query with its value — the price ceiling, the size, or the
    keywords it searched for". Target 3 of 3. '"No results" or "Try a
    different search" fails this.'
    """
    if run["crashed"]:
        return False, f"crashed: {run['crashed']}"
    s = run["session"] or {}
    if s.get("search_results"):
        return False, "this query was not empty, so 5(b) was never exercised"
    message = s.get("error") or ""
    parsed = s.get("parsed") or {}
    if not message.strip():
        return False, "session['error'] was empty"

    quoted = []
    ceiling = parsed.get("max_price")
    if ceiling is not None and re.search(
        r"(?<![\d.])" + re.escape(f"{float(ceiling):g}") + r"(?![\d])", message
    ):
        quoted.append(f"the ${ceiling:g} ceiling")
    size = parsed.get("size")
    if size and size.lower() in message.lower():
        quoted.append(f"the size {size}")
    hit_kw = [k for k in (parsed.get("keywords") or []) if k.lower() in message.lower()]
    if hit_kw:
        quoted.append(f"the keywords it searched ({', '.join(hit_kw)})")

    if not quoted:
        return False, (
            f"the message names no constraint with its value. Parsed "
            f"max_price={ceiling!r}, size={size!r}, "
            f"keywords={parsed.get('keywords')!r}; message was "
            f"{message.strip()[:140]!r}"
        )
    return True, "names " + " and ".join(quoted)


# ── Reducing runs into tries ──────────────────────────────────────────────────

def _runs_for(data, criterion):
    """Every scenario feeding a criterion, in scenarios.py order."""
    out = []
    for row in data["rows"]:
        if criterion in (row["scenario"].get("criteria") or []):
            out.append(row)
    return out


def _and_over_set(rows, rep, checker):
    """
    One try of a criterion whose set is several queries: it passes only if
    every query in the set passed on this repetition.

    This is the strict reduction and it is deliberate. A criterion that says
    "across 5 fit cards, every card contains the price" is not satisfied by
    four of them containing it, so a try in which one card dropped the price
    is a failed try, not four fifths of one.
    """
    faults = []
    for row in rows:
        ok, why = checker(row["tries"][rep])
        if not ok:
            faults.append(f"{row['scenario']['name']}: {why}")
    return (not faults), faults


def score(data) -> list[dict]:
    """Every criterion, every try, with a reason for each failure."""
    n = data["tries"]
    results = []

    # ── 1 ──
    rows1 = _runs_for(data, 1)
    tries, notes = [], []
    for rep in range(n):
        ok, faults = _and_over_set(rows1, rep, check_1)
        tries.append(ok)
        notes.append(faults)
    results.append({
        "key": "1",
        "name": "A matching query completes all three tools",
        "target": "4 of 5", "need": 4, "of": n,
        "tries": tries, "notes": notes,
        "set": f"{len(rows1)} matching queries per try",
    })

    # ── 2 ──
    rows2 = _runs_for(data, 2)
    tries, notes = [], []
    for rep in range(n):
        ok, faults = _and_over_set(rows2, rep, check_2)
        tries.append(ok)
        notes.append(faults)
    results.append({
        "key": "2",
        "name": "An impossible query stops before the second tool",
        "target": "5 of 5", "need": 5, "of": n,
        "tries": tries, "notes": notes,
        "set": f"{len(rows2)} impossible query per try",
    })

    # ── 3 ──
    rows3 = _runs_for(data, 3)
    tries, notes = [], []
    for rep in range(n):
        ok, faults = _and_over_set(rows3, rep, check_3)
        tries.append(ok)
        notes.append(faults)
    results.append({
        "key": "3",
        "name": "The item the search found is the item the next tool received",
        "target": "5 of 5", "need": 5, "of": n,
        "tries": tries, "notes": notes,
        "set": f"{len(rows3)} matching queries per try",
    })

    # ── 4 ── per-card checks, plus the distinct-openings clause over the set
    rows4 = _runs_for(data, 4)
    tries, notes = [], []
    for rep in range(n):
        ok, faults = _and_over_set(rows4, rep, check_4_card)
        openings = []
        for row in rows4:
            card = ((row["tries"][rep]["session"] or {}).get("fit_card") or "").strip()
            sents = _sentences(card)
            if sents:
                openings.append(sents[0].strip().lower())
        duplicates = len(openings) - len(set(openings))
        if duplicates:
            seen, dup = set(), []
            for o in openings:
                if o in seen:
                    dup.append(o[:70])
                seen.add(o)
            faults = list(faults) + [
                f"the 5 cards do not have 5 distinct opening sentences — "
                f"{duplicates} repeat: {dup}"
            ]
            ok = False
        tries.append(ok)
        notes.append(faults)
    results.append({
        "key": "4",
        "name": "The fit card names the item, its price and its platform, every time",
        "target": "5 of 5", "need": 5, "of": n,
        "tries": tries, "notes": notes,
        "set": f"{len(rows4)} cards per try, openings compared within the try",
    })

    # ── 5 ── two parts, both must hold
    rows5 = _runs_for(data, 5)
    rows5a = [r for r in rows5 if r["scenario"].get("expect_item")]
    rows5b = [r for r in rows5 if not r["scenario"].get("expect_item")]

    a_tries, a_notes = [], []
    for rep in range(n):
        ok, faults = _and_over_set(rows5a, rep, check_5a)
        a_tries.append(ok)
        a_notes.append(faults)

    # 5(b)'s target is 3 of 3 for 3 different queries, so a try is a query.
    # The path makes no model call, so every repetition should be identical;
    # that is asserted rather than assumed, and reported if it ever is not.
    b_tries, b_notes = [], []
    for row in rows5b:
        per_rep = [check_5b(row["tries"][rep]) for rep in range(n)]
        ok = all(p[0] for p in per_rep)
        stable = len({p[0] for p in per_rep}) == 1
        faults = [] if ok else [f"{row['scenario']['name']}: {per_rep[0][1]}"]
        if not stable:
            faults.append(
                f"{row['scenario']['name']}: the result was not identical "
                f"across all {n} repetitions of a path that makes no model "
                f"call — that is a defect in itself"
            )
            ok = False
        b_tries.append(ok)
        b_notes.append(faults)

    combined, combined_notes = [], []
    for rep in range(n):
        ok = a_tries[rep]
        faults = list(a_notes[rep])
        if rep < len(b_tries):
            ok = ok and b_tries[rep]
            faults += b_notes[rep]
        combined.append(ok)
        combined_notes.append(faults)

    results.append({
        "key": "5",
        "name": "A stated price ceiling is never exceeded, and the empty-search "
                "message is actionable",
        "target": "(a) 5 of 5, (b) 3 of 3", "need": n, "of": n,
        "tries": combined, "notes": combined_notes,
        "set": f"(a) {len(rows5a)} ceilinged queries per try; "
               f"(b) {len(rows5b)} different empty cases, one per try",
        "parts": {
            "5(a) no result above the stated ceiling": {
                "tries": a_tries, "notes": a_notes, "need": n, "of": n,
                "target": "5 of 5",
            },
            "5(b) the empty-search message quotes a constraint": {
                "tries": b_tries, "notes": b_notes, "need": len(rows5b),
                "of": len(rows5b), "target": "3 of 3",
            },
        },
    })
    return results


def verdict(row) -> str:
    passes = sum(1 for t in row["tries"] if t)
    total = len(row["tries"])
    met = passes >= row["need"]
    return f"{'MET' if met else 'MISSED'} ({passes}/{total})"


# ── Output ────────────────────────────────────────────────────────────────────

def render(data, results) -> str:
    n = data["tries"]
    out = [
        f"# Run log — {data['label'] or 'unlabelled'}",
        "",
        f"- Scored by: `score.py::score`, applying `criteria.md`",
        f"- Runs by: `run_eval.py::main` · loop `agent.py::run_agent`",
        f"- Tries per scenario: {n}, caching {'ON — WRONG' if data['cache_enabled'] else 'off'}",
        f"- Temperature: {data['temperature']}",
        f"- When: {data['when']}",
        "",
        f"| Criterion | Target | {' | '.join(f'Try {i}' for i in range(1, n + 1))} | Verdict |",
        f"|---|---|{'|'.join(['---'] * n)}|---|",
    ]
    for row in results:
        cells = " | ".join("PASS" if t else "FAIL" for t in row["tries"])
        pad = " | ".join([""] * max(0, n - len(row["tries"])))
        line = f"| {row['key']}. {row['name']} | {row['target']} | {cells}"
        if pad:
            line += f" | {pad}"
        out.append(line + f" | {verdict(row)} |")

    # 5's two parts, broken out
    five = [r for r in results if r["key"] == "5"][0]
    out += ["", "Criterion 5 has two parts and the row above is the conjunction. "
                "Separately:", "",
            f"| Part | Target | {' | '.join(f'Try {i}' for i in range(1, n + 1))} | Verdict |",
            f"|---|---|{'|'.join(['---'] * n)}|---|"]
    for name, part in five["parts"].items():
        cells = ["PASS" if t else "FAIL" for t in part["tries"]]
        cells += ["n/a"] * (n - len(cells))
        passes = sum(1 for t in part["tries"] if t)
        met = passes >= part["need"]
        out.append(
            f"| {name} | {part['target']} | {' | '.join(cells)} | "
            f"{'MET' if met else 'MISSED'} ({passes}/{len(part['tries'])}) |"
        )

    out += ["", "## Why each failing try failed", ""]
    any_fault = False
    for row in results:
        faults = [(i + 1, f) for i, f in enumerate(row["notes"]) if f]
        if not faults:
            continue
        any_fault = True
        out.append(f"**Criterion {row['key']}** — {row['set']}")
        out.append("")
        for i, fs in faults:
            for f in fs:
                out.append(f"- try {i}: {f}")
        out.append("")
    if not any_fault:
        out += ["Nothing failed.", ""]

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Apply criteria.md to a run.")
    ap.add_argument("path", nargs="?", help="a results/*.json written by run_eval.py")
    ap.add_argument("--latest", metavar="LABEL",
                    help="score the newest run with this label, e.g. 'before'")
    ap.add_argument("-o", "--out", help="write the run log here as well as printing it")
    args = ap.parse_args()

    if args.latest:
        found = sorted(config.RESULTS_DIR.glob(f"run_*_{args.latest}.json"))
        if not found:
            print(f"No results/run_*_{args.latest}.json yet. Run "
                  f"`python run_eval.py --label {args.latest}` first.", file=sys.stderr)
            sys.exit(1)
        path = found[-1]
    elif args.path:
        path = Path(args.path)
    else:
        ap.error("give a path or --latest LABEL")

    data = json.loads(path.read_text(encoding="utf-8"))
    results = score(data)
    text = render(data, results)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n(also written to {args.out})", file=sys.stderr)


if __name__ == "__main__":
    main()
