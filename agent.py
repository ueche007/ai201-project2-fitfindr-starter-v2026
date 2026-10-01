"""
The FitFindr planning loop.

This is the file that makes FitFindr an agent rather than a script: it decides
which tool to run next based on what the last one returned.

There are two branches, both documented in README.md under **Planning Loop**:

  1. **Required.** If `search_listings` comes back empty, stop before
     `suggest_outfit` and put a message naming what to loosen in
     `session["error"]`.
  2. **Stretch.** If `compare_prices` says the top candidate is overpriced,
     reject it and go round again with the next one, rather than styling
     whatever the search happened to rank first.

The second one is why this is a loop with a counter and not a straight line.

    python agent.py          runs both example paths below
"""

import re

import config  # noqa: F401 — imported for its .env load and Windows console fix
import trace
from tools import search_listings, suggest_outfit, create_fit_card, compare_prices
from utils.data_loader import load_listings
from generate import ModelUnavailable  # noqa: F401 — handled in unit 4


# ── Query parsing ─────────────────────────────────────────────────────────────
#
# Regex, not a model call. Parsing is the one deterministic step in a run, and
# keeping it deterministic is the only reason criterion 5 can be checked at
# all — a parser that varied between tries would make "the ceiling was never
# exceeded" unfalsifiable.
#
# The price is matched FIRST and its matched span is cut out of the string
# before the size is looked for. Otherwise "under $30" leaves a bare 30 behind
# and the size patterns read it as a waist measurement, which silently turns a
# budget into a size filter.

_PRICE_PATTERNS = (
    r"(?:under|below|less than|no more than|cheaper than|up to|max(?:imum)?(?:\s+of)?)\s*\$?\s*(\d+(?:\.\d+)?)",
    r"\$\s*(\d+(?:\.\d+)?)\s*(?:or\s+(?:less|under|below)|max(?:imum)?)",
    r"budget(?:\s+of)?\s*\$?\s*(\d+(?:\.\d+)?)",
)

_LETTERS = r"xxs|xs|s|m|l|xl|xxl|xxxl"

_SIZE_PATTERNS = (
    rf"\bsize\s*[:\-]?\s*(us\s*\d+(?:\.\d+)?)\b",
    rf"\bsize\s*[:\-]?\s*(w\s*\d+(?:\s*l\s*\d+)?)\b",
    rf"\bsize\s*[:\-]?\s*({_LETTERS})\b",
    rf"\bsize\s*[:\-]?\s*(\d+(?:\.\d+)?)\b",
    rf"\b(us\s*\d+(?:\.\d+)?)\b",
    rf"\b(w\s*\d+(?:\s*l\s*\d+)?)\b",
    rf"\bin\s+(?:an?\s+)?({_LETTERS})\b",
)


def _number(text: str) -> str:
    """A float formatted the way a person writes a price: 30.0 → "30"."""
    try:
        return f"{float(text):g}"
    except (TypeError, ValueError):
        return str(text)


def parse_query(query: str) -> dict:
    """
    Pull a description, a size and a price ceiling out of a plain sentence.

    Args:
        query: what the user typed, e.g. "vintage graphic tee under $30, size M".

    Returns:
        A dict with four keys, always all four:
            description (str)        — the words left over, for keyword search
            size        (str | None) — the size as written, e.g. "M", "US 8"
            max_price   (float|None) — the ceiling, or None if none was named
            keywords    (list[str])  — description split into search words,
                                       kept so the no-results message can
                                       quote what was actually searched for
    """
    text = (query or "").lower()
    remaining = text

    max_price = None
    for pattern in _PRICE_PATTERNS:
        match = re.search(pattern, remaining)
        if match:
            max_price = float(match.group(1))
            remaining = remaining[: match.start()] + " " + remaining[match.end():]
            break

    size = None
    for pattern in _SIZE_PATTERNS:
        match = re.search(pattern, remaining)
        if match:
            size = re.sub(r"\s+", " ", match.group(1)).strip().upper()
            remaining = remaining[: match.start()] + " " + remaining[match.end():]
            break

    description = re.sub(r"[^a-z0-9'\s-]", " ", remaining)
    description = re.sub(r"\s+", " ", description).strip()

    # Imported here rather than at module scope: _keywords is the same
    # tokeniser search_listings uses, and the no-results message has to quote
    # the words that were really searched, not a second approximation of them.
    from tools import _keywords

    return {
        "description": description,
        "size": size,
        "max_price": max_price,
        "keywords": _keywords(description),
    }


def _no_results_message(parsed: dict) -> str:
    """
    The message for the empty-search branch.

    Criterion 5(b) is what shapes this: it has to name at least one specific
    constraint *with its value*, because a user who knows nothing about the
    code cannot act on "no results". So it quotes the ceiling, the size and the
    keywords actually applied, then says which one to loosen.
    """
    if not parsed["keywords"]:
        return (
            f"I couldn't find any searchable words in {parsed['description']!r}. "
            f"Describe the garment itself — a category like 'jacket' or "
            f"'jeans', or a style like 'vintage', 'y2k', 'grunge'."
        )

    applied = [f"keywords: {', '.join(parsed['keywords'])}"]
    if parsed["max_price"] is not None:
        applied.append(f"price at or under ${_number(parsed['max_price'])}")
    if parsed["size"]:
        applied.append(f"size {parsed['size']}")

    fixes = []
    if parsed["max_price"] is not None:
        fixes.append(f"raise the ${_number(parsed['max_price'])} ceiling")
    if parsed["size"]:
        fixes.append(f"drop or widen the size filter ({parsed['size']})")
    fixes.append(
        "or use words closer to how a seller would title it — this data runs "
        "on terms like vintage, y2k, 90s, graphic tee, denim, oversized, "
        "grunge, linen"
    )

    return (
        f"Nothing in the {len(load_listings())} listings matches all of: "
        f"{'; '.join(applied)}.\n"
        f"  To get results, {', '.join(fixes)}."
    )


# ── session state ─────────────────────────────────────────────────────────────

def new_session(query: str, wardrobe: dict) -> dict:
    """
    A fresh session for one user interaction.

    The session is the single source of truth for a run. Every tool result goes
    in here, and the next tool reads it back out. Nothing is passed straight
    from one call into the next, which is what makes the state visible to the
    trace and checkable by criterion 3.

    Three fields past the starter's own, all for the second branch:
    `price_check`, `rejected`, `price_warning`.
    """
    return {
        "query": query,              # what the user typed
        "parsed": {},                # description / size / max_price pulled out of it
        "search_results": [],        # everything search_listings returned
        "price_check": None,         # compare_prices on the accepted candidate
        "rejected": [],              # candidates the price branch turned down
        "price_warning": None,       # set when every candidate was overpriced
        "selected_item": None,       # the one chosen — goes into suggest_outfit
        "wardrobe": wardrobe,        # the user's wardrobe
        "outfit_suggestion": None,   # what suggest_outfit returned
        "fit_card": None,            # what create_fit_card returned
        "error": None,               # set when the run ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Run the loop once and return the finished session.

    Args:
        query:    what the user asked for, in plain language
                  (e.g. "vintage graphic tee under $30, size M").
        wardrobe: a wardrobe dict — get_example_wardrobe(),
                  get_empty_wardrobe(), or a remembered one from
                  utils/style_memory.py.

    Returns:
        The session dict. Check session["error"] first — if it isn't None, the
        run ended early and the later fields are still None.
    """
    session = new_session(query, wardrobe)
    iterations = 0

    # ── Step 1: parse the query ───────────────────────────────────────────
    session["parsed"] = parse_query(query)
    trace.step(
        "parse_query",
        inputs=query,
        returned=(
            f"description={session['parsed']['description']!r}, "
            f"size={session['parsed']['size']!r}, "
            f"max_price={session['parsed']['max_price']!r}"
        ),
    )

    # ── Step 2: search ────────────────────────────────────────────────────
    session["search_results"] = search_listings(
        description=session["parsed"]["description"],
        size=session["parsed"]["size"],
        max_price=session["parsed"]["max_price"],
    )
    trace.step(
        "search_listings",
        inputs=(
            f"description={session['parsed']['description']!r}, "
            f"size={session['parsed']['size']!r}, "
            f"max_price={session['parsed']['max_price']!r}"
        ),
        returned=session["search_results"],
    )

    # ── BRANCH 1 (required): nothing came back ────────────────────────────
    if not session["search_results"]:
        session["error"] = _no_results_message(session["parsed"])
        trace.step(
            "branch",
            returned="search_results == [] (empty list)",
            note="stopping before suggest_outfit — nothing to style",
        )
        return session

    # ── BRANCH 2 (stretch): reject overpriced candidates, re-plan ─────────
    #
    # This is the part that makes it a loop. Each turn price-checks one
    # candidate and decides from the result whether to accept it or go round
    # again, so the number of iterations depends on the data rather than being
    # fixed in the code — which is also why check_iterations earns its keep.
    for rank, candidate in enumerate(session["search_results"], start=1):
        iterations += 1
        trace.check_iterations(iterations)

        check = compare_prices(candidate)
        trace.step(
            "compare_prices",
            inputs=f"candidate {rank} of {len(session['search_results'])}: "
                   f"{candidate['id']} at ${_number(candidate['price'])}",
            returned=check["verdict"],
            note=check["summary"],
        )

        if check["verdict"] != "overpriced":
            session["selected_item"] = candidate
            session["price_check"] = check
            trace.step(
                "select_item",
                inputs=f"candidate {rank} of {len(session['search_results'])}",
                returned=candidate,
                note=f"session['selected_item']['id'] = {candidate['id']}",
            )
            break

        session["rejected"].append({
            "id": candidate["id"],
            "title": candidate["title"],
            "price": candidate["price"],
            "reason": check["summary"],
        })
        trace.step(
            "branch",
            returned=f"rejected {candidate['id']}",
            note="overpriced — going round again with the next candidate",
        )
    else:
        # Every candidate was overpriced. A styled overpriced item is still
        # more useful than nothing, so the top-ranked one is taken anyway and
        # the warning says so. It stays in `rejected` as well — that list is a
        # record of what the branch judged, not of what was discarded.
        fallback = session["search_results"][0]
        session["selected_item"] = fallback
        session["price_check"] = compare_prices(fallback)
        count = len(session["search_results"])
        session["price_warning"] = (
            f"The only match came out above the going rate for its category. "
            if count == 1 else
            f"All {count} matches came out above the going rate for their "
            f"categories. "
        ) + (
            f"Showing the best keyword match anyway — "
            f"{session['price_check']['summary']}"
        )
        trace.step(
            "select_item",
            inputs=f"all {len(session['search_results'])} candidates overpriced",
            returned=fallback,
            note=f"session['selected_item']['id'] = {fallback['id']} "
                 f"(accepted with a price warning)",
        )

    # ── Step 3: suggest an outfit ─────────────────────────────────────────
    # Read back OUT of the session rather than reusing `candidate`, so what
    # reaches this tool is provably what the session holds.
    item = session["selected_item"]
    wardrobe_items = (session["wardrobe"] or {}).get("items") or []

    session["outfit_suggestion"] = suggest_outfit(item, session["wardrobe"])
    trace.step(
        "suggest_outfit",
        inputs=f"selected_item id = {item['id']} (read back from session), "
               f"wardrobe items = {len(wardrobe_items)}",
        returned=session["outfit_suggestion"],
        note="empty wardrobe — general advice" if not wardrobe_items else "",
    )

    # ── Step 4: write the fit card ────────────────────────────────────────
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )
    trace.step(
        "create_fit_card",
        inputs=f"outfit = {len(session['outfit_suggestion'])} chars, "
               f"selected_item id = {session['selected_item']['id']}",
        returned=session["fit_card"],
    )

    return session


# ── running it directly ───────────────────────────────────────────────────────

def _show(session: dict) -> None:
    if session["error"]:
        print(f"  stopped: {session['error']}")
        print(f"  fit_card is {session['fit_card']!r} — it should still be None here")
        return

    item = session["selected_item"] or {}
    print(f"  found:    {item.get('title')} — ${item.get('price')} on {item.get('platform')}")
    if session["rejected"]:
        print(f"  rejected: {len(session['rejected'])} overpriced candidate(s) first")
    if session["price_warning"]:
        print(f"  warning:  {session['price_warning']}")
    print(f"  outfit:   {session['outfit_suggestion']}")
    print(f"  fit card: {session['fit_card']}")


if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe

    # Running this file directly is for watching the loop, so trace printing
    # is on. app.py leaves it off unless --trace is passed.
    trace.start_trace()

    print("=== A query the data can match ===")
    _show(run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    ))

    print("\n=== A query it can't ===")
    trace.start_trace()
    _show(run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    ))

    print(
        "\nThe second one should stop before the fit card. If both paths look "
        "the same,\nthe branch isn't doing anything yet."
    )
