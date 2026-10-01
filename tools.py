"""
The FitFindr tools.

Each one is a standalone function, callable and testable on its own before any
of them are wired into the loop.

    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)             → str
    create_fit_card(outfit, new_item)              → str
    compare_prices(item, listings)                 → dict   (stretch)

Specs for all four are in README.md under **Tool Inventory**, written before
any of this was implemented. The empty case of each one is part of the spec,
because that is what the loop in agent.py branches on.

Only `search_listings` and `compare_prices` are deterministic. The other two
call the model through `generate()`, which handles pacing and caching.
"""

import re
import statistics

import config
from generate import generate
from utils.data_loader import load_listings


# ── Size matching ─────────────────────────────────────────────────────────────
#
# Sizes in listings.json span four scales that mean different things, so a
# substring test is wrong rather than merely sloppy: `"s" in "us 9"` is True,
# which returns shoes to someone who asked for a small top, and `"l" in "xl"`
# is True, which returns XL to someone who asked for L.
#
# Both the request and the listing are classified into a family, and a listing
# can only match inside its own family. See notes/data-notes.md for the full
# survey of the 22 distinct size strings this has to cope with.

_LETTER_SIZES = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"}

# Above this, a bare number is read as a waist measurement; at or below it, a
# US shoe size. The data has waists W27–W32 and shoes US 7–US 9, so anything
# in between would be ambiguous — there is nothing in between.
_SHOE_SIZE_CEILING = 16.0


def _size_family(raw: str | None) -> tuple[str | None, set[str]]:
    """
    Classify a size string into (family, tokens).

    Families: "one_size", "shoe", "waist", "letter", "other". A None or blank
    size returns (None, set()), which callers read as "no size constraint".

        "S/M"                  → ("letter", {"S", "M"})
        "XL (oversized)"       → ("letter", {"XL"})
        "W30 L30"              → ("waist",  {"30"})
        "US 8.5"               → ("shoe",   {"8.5"})
        "One Size / Oversized" → ("one_size", {"one size"})
        "8"                    → ("shoe",   {"8"})
        "30"                   → ("waist",  {"30"})
    """
    text = (raw or "").strip().lower()
    if not text:
        return None, set()

    # Checked before anything else, because "One Size / Oversized" would
    # otherwise fall through to the letter branch and tokenise to nonsense.
    if "one size" in text:
        return "one_size", {"one size"}

    # "XL (oversized)" and "XL (fits oversized)" are both just XL.
    text = re.sub(r"\([^)]*\)", " ", text).strip()

    shoe = re.findall(r"us\s*(\d+(?:\.\d+)?)", text)
    if shoe:
        return "shoe", {f"{float(n):g}" for n in shoe}

    # Matched before the letter branch so "W30 L30" is a waist, not an L.
    waist = re.findall(r"\bw\s*(\d+)", text)
    if waist:
        return "waist", {str(int(n)) for n in waist}

    tokens = {t.upper() for t in re.split(r"[/\s,]+", text) if t}
    letters = tokens & _LETTER_SIZES
    if letters:
        return "letter", letters

    bare = re.fullmatch(r"(\d+(?:\.\d+)?)", text)
    if bare:
        number = float(bare.group(1))
        if number <= _SHOE_SIZE_CEILING:
            return "shoe", {f"{number:g}"}
        return "waist", {str(int(number))}

    return "other", tokens


def _size_matches(requested: str | None, listing_size: str | None) -> bool:
    """
    True when a listing's size satisfies a requested size.

    No requested size matches everything. A One Size listing matches every
    request. Otherwise the families have to agree and the tokens have to
    overlap, so a request for "M" matches "M" and "S/M" but not "W30", "US 8"
    or "XL".
    """
    request_family, request_tokens = _size_family(requested)
    if request_family is None:
        return True

    listing_family, listing_tokens = _size_family(listing_size)
    if listing_family == "one_size":
        return True
    if listing_family != request_family:
        return False
    return bool(request_tokens & listing_tokens)


# ── Keyword scoring ───────────────────────────────────────────────────────────
#
# Weights, highest first. A keyword scores the weight of the best field it
# appears in, and a listing's score is the sum over the keywords. Title and
# style tags outrank description because a word in the title is what the seller
# thinks the item *is*, where a word in the description is often incidental —
# "no rips or stains" should not make something a match for "rips".

_FIELD_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("title", 3.0),
    ("style_tags", 2.0),
    ("category", 2.0),
    ("brand", 1.0),
    ("colors", 1.0),
    ("description", 1.0),
)

# Words that carry no search signal. Kept deliberately short: every word
# removed here is a word that can no longer match, and over-pruning is how a
# search starts missing things for reasons nobody can see.
_STOPWORDS = {
    "a", "an", "and", "any", "are", "around", "for", "find", "from", "get",
    "got", "have", "i", "im", "in", "is", "it", "like", "looking", "max",
    "me", "my", "need", "of", "or", "over", "size", "some", "something",
    "that", "the", "them", "to", "under", "want", "with", "would",
}


def _keywords(description: str | None) -> list[str]:
    """
    Pull the searchable words out of a description.

    Keeps digits so "90s" and "y2k" survive, drops single characters and
    stopwords, and de-duplicates while preserving order so a word repeated in
    the query cannot score twice.
    """
    words = re.findall(r"[a-z0-9']+", (description or "").lower())
    seen: list[str] = []
    for word in words:
        if len(word) > 1 and word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return seen


def _field_text(listing: dict, field: str) -> str:
    """
    One listing field as lowercase searchable text.

    Lists are joined; None becomes "". `brand` is None on 32 of the 40
    listings, so this is the normal case rather than an edge one.
    """
    value = listing.get(field)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value).lower()
    return str(value).lower()


def _keyword_hits(keyword: str, text: str) -> bool:
    """
    True when a keyword appears in a field's text.

    Substring rather than whole-word, so "tee" matches "Baby Tee" and "boot"
    matches "Chelsea Boots". A trailing "s" is also tried stripped, so a query
    for "sneakers" matches a listing titled "Platform Sneaker". There is no
    stemming beyond that and no synonyms at all — which is the known weakness
    criterion 1 sets its target around.
    """
    if keyword in text:
        return True
    if keyword.endswith("s") and len(keyword) > 2 and keyword[:-1] in text:
        return True
    return False


def _score(listing: dict, keywords: list[str]) -> float:
    """Sum, over the keywords, of the best-weighted field each one hits."""
    total = 0.0
    for keyword in keywords:
        best = 0.0
        for field, weight in _FIELD_WEIGHTS:
            if weight > best and _keyword_hits(keyword, _field_text(listing, field)):
                best = weight
        total += best
    return total


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the listings data for items matching a description, and optionally a
    size and a price ceiling.

    The one tool that does not call the model, which makes it the one to test
    exhaustively.

    Args:
        description: keywords describing what the user wants
                     (e.g. "vintage graphic tee").
        size:        a size string to filter by, or None to skip size
                     filtering. Matched by family — see _size_matches.
        max_price:   maximum price, inclusive, or None to skip price filtering.

    Returns:
        A list of matching listing dicts, best match first and cheaper first
        among equal scores, at most config.SEARCH_RESULT_LIMIT of them. Each
        dict is a copy of the listing with one key added, `match_score`
        (float), the score it was ranked on.

        Returns an empty list when nothing matches — an empty list, not None,
        and not an exception. agent.py::run_agent branches on this.

    Test it from a terminal:
        python -c "from tools import search_listings; print(search_listings('graphic tee', max_price=30))"
    """
    keywords = _keywords(description)

    # No usable keywords means no basis for a match. Returning everything here
    # would be worse than returning nothing: the loop would style an arbitrary
    # item and the user would never learn their query said nothing.
    if not keywords:
        return []

    matches: list[dict] = []
    for listing in load_listings():
        price = listing.get("price")
        if max_price is not None and (price is None or float(price) > float(max_price)):
            continue
        if not _size_matches(size, listing.get("size")):
            continue

        score = _score(listing, keywords)
        if score <= 0:
            continue

        scored = dict(listing)
        scored["match_score"] = score
        matches.append(scored)

    # Highest score first; cheaper first among ties, which is the tiebreak a
    # thrifter would want; id last so the order is total and runs are
    # reproducible.
    matches.sort(key=lambda m: (-m["match_score"], m["price"], m["id"]))
    return matches[: config.SEARCH_RESULT_LIMIT]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

_STYLIST_SYSTEM = (
    "You are a secondhand-fashion stylist. You are specific and you are brief. "
    "You name actual garments rather than describing vibes, you never invent "
    "clothes the user did not say they own, and you never mention a brand "
    "unless one was given to you."
)


def _money(price) -> str:
    """
    A price as it would be written in a caption.

    Every price in the data is a whole number of dollars stored as a float, so
    str() gives "$18.0" and the model copies that straight into the caption.
    Trailing zeros come off; a genuine cents value keeps them.
    """
    try:
        value = float(price)
    except (TypeError, ValueError):
        return str(price)
    return f"{value:.0f}" if value == int(value) else f"{value:.2f}"


def _describe_listing(listing: dict) -> str:
    """One compact line describing a listing, for a prompt."""
    tags = ", ".join(listing.get("style_tags") or []) or "no tags"
    colors = ", ".join(listing.get("colors") or []) or "unspecified colour"
    brand = listing.get("brand") or "unbranded"
    return (
        f"{listing.get('title')} — {listing.get('category')}, "
        f"size {listing.get('size')}, {colors}, {brand}, "
        f"condition {listing.get('condition')}, "
        f"${_money(listing.get('price'))} on {listing.get('platform')}. "
        f"Style tags: {tags}. "
        f"Seller's description: {listing.get('description')}"
    )


def _describe_wardrobe(items: list[dict]) -> str:
    """The wardrobe as a grouped list, so the model can pick from it by name."""
    by_category: dict[str, list[str]] = {}
    for item in items:
        line = item.get("name", "unnamed item")
        if item.get("notes"):
            line += f" ({item['notes']})"
        by_category.setdefault(item.get("category", "other"), []).append(line)

    blocks = []
    for category in ("tops", "bottoms", "outerwear", "shoes", "accessories"):
        if category in by_category:
            listed = "; ".join(by_category.pop(category))
            blocks.append(f"{category}: {listed}")
    for category, listed in by_category.items():
        blocks.append(f"{category}: {'; '.join(listed)}")
    return "\n".join(blocks)


def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest one or two outfits.

    Calls the model through generate().

    Args:
        new_item: a listing dict — the item the user is considering.
        wardrobe: a wardrobe dict with an 'items' key holding a list of items.
                  May be empty.

    Returns:
        A non-empty string with outfit suggestions. With a stocked wardrobe the
        suggestions name the user's own pieces.

        With an empty wardrobe, returns general styling advice behind a line
        saying the advice is general because no wardrobe is saved.

        With no usable item, returns
        "No item to style — search_listings returned nothing." — reaching this
        tool without an item means the loop's branch failed, and the string
        should say so rather than quietly produce plausible prose.

    Test it from a terminal:
        python -c "from tools import suggest_outfit; from utils.data_loader import get_example_wardrobe, load_listings; print(suggest_outfit(load_listings()[0], get_example_wardrobe()))"
    """
    if not isinstance(new_item, dict) or not new_item:
        return "No item to style — search_listings returned nothing."

    items = (wardrobe or {}).get("items") or []
    item_line = _describe_listing(new_item)

    if not items:
        prompt = (
            "Someone is considering buying this secondhand item:\n\n"
            f"{item_line}\n\n"
            "They have no wardrobe saved, so you do not know what they own. "
            "Give general styling advice for this piece in 3 or 4 sentences: "
            "what kinds of garments it goes with, what to avoid putting it "
            "with, and one occasion it suits. Describe garment types, not "
            "specific items you are pretending they own."
        )
        advice = generate(prompt, system=_STYLIST_SYSTEM).strip()
        if not advice:
            advice = (
                f"Style the {new_item.get('category', 'piece')} simply: let it "
                f"be the loudest thing in the outfit and keep everything else "
                f"plain."
            )
        return (
            "No wardrobe saved yet, so this is general styling advice rather "
            "than outfits from your own clothes.\n\n" + advice
        )

    prompt = (
        "Someone is considering buying this secondhand item:\n\n"
        f"{item_line}\n\n"
        "This is what they already own:\n\n"
        f"{_describe_wardrobe(items)}\n\n"
        "Suggest two outfits built around the new item. Each outfit must name "
        "at least two pieces from the list above, using the names as written. "
        "Two or three sentences per outfit. Do not suggest anything they do "
        "not own, and say briefly why each combination works."
    )
    suggestion = generate(prompt, system=_STYLIST_SYSTEM).strip()
    if not suggestion:
        # generate() raises ModelUnavailable when it cannot reach the service,
        # so an empty string here means a reply that was genuinely blank. The
        # spec says this tool returns a non-empty string, so it returns one.
        names = ", ".join(i.get("name", "") for i in items[:3])
        suggestion = (
            f"The model returned nothing for this item. Starting points from "
            f"your wardrobe: {names}."
        )
    return suggestion


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

_CAPTION_SYSTEM = (
    "You write captions for secondhand-fashion posts. You sound like a person "
    "who thrifts, not like a product page. You never use hashtags, you never "
    "open two different captions the same way, and you never mention a brand "
    "unless one was given to you."
)


def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Write a short caption someone would actually post about the find.

    Calls the model through generate().

    Args:
        outfit:   the outfit suggestion string from suggest_outfit().
        new_item: the listing dict for the item.

    Returns:
        A two-to-four sentence caption naming the item, its price and its
        platform once each.

        Returns "No fit card — there was no outfit to write about." when
        `outfit` is empty, whitespace-only, or not a string, and makes no model
        call in that case. Returns "No fit card — there was no item to write
        about." when `new_item` is missing or not a dict. Neither raises.

    Written at config.TEMPERATURE (0.9), so the same item gives different
    wording run to run. That is intended — a caption that reads identically
    for two items is a template. Criterion 4 in criteria.md is what keeps the
    variation inside bounds.

    Test it from a terminal:
        python -c "from tools import create_fit_card; from utils.data_loader import load_listings; print(create_fit_card('jeans and white sneakers', load_listings()[0]))"
    """
    if not isinstance(outfit, str) or not outfit.strip():
        return "No fit card — there was no outfit to write about."
    if not isinstance(new_item, dict) or not new_item:
        return "No fit card — there was no item to write about."

    # Price and platform are passed in their own labelled lines rather than
    # buried in the item description, because criterion 4 requires both in
    # every card and a labelled line is harder for the model to drop.
    prompt = (
        "Write a caption for a post about this secondhand find.\n\n"
        f"The item: {new_item.get('title')}\n"
        f"Price: ${_money(new_item.get('price'))}\n"
        f"Platform: {new_item.get('platform')}\n"
        f"Colours: {', '.join(new_item.get('colors') or []) or 'unspecified'}\n"
        f"Style: {', '.join(new_item.get('style_tags') or []) or 'unspecified'}\n\n"
        f"How it is being worn:\n{outfit.strip()}\n\n"
        "Rules:\n"
        "- Two to four sentences, under 400 characters in total.\n"
        "- Name the item or what kind of thing it is in the first sentence.\n"
        f"- State the price (${_money(new_item.get('price'))}) exactly once.\n"
        f"- Name the platform ({new_item.get('platform')}) exactly once.\n"
        "- Be specific about the feel of the outfit rather than calling it cute.\n"
        "- No hashtags, no emoji-only sentences, no opening with 'Just'.\n"
        "- Output the caption only, with no preamble and no quote marks."
    )
    card = generate(prompt, system=_CAPTION_SYSTEM).strip()
    if not card:
        return (
            f"{new_item.get('title')} — ${_money(new_item.get('price'))} on "
            f"{new_item.get('platform')}. The model returned an empty caption."
        )
    return card


# ── Tool 4: compare_prices (stretch) ─────────────────────────────────────────

# Fewer than this many comparables is not a distribution, so no verdict is
# given. Three is the smallest number with a meaningful median.
_MIN_COMPARABLES = 3

# Fractions of the comparable median.
_GOOD_DEAL_AT = 0.85
_FAIR_UP_TO = 1.15


def _unknown_price_check(count: int, reason: str) -> dict:
    """The no-verdict result. Same seven keys as a real one, by design."""
    return {
        "verdict": "unknown",
        "comparable_count": count,
        "median_price": None,
        "min_price": None,
        "max_price": None,
        "delta_vs_median": None,
        "summary": reason,
    }


def compare_prices(item: dict, listings: list[dict] | None = None) -> dict:
    """
    Work out whether one listing is fairly priced against comparable listings.

    Deterministic — no model call.

    Args:
        item:     the listing dict to price-check.
        listings: the pool to compare against. None loads the full dataset,
                  which is the normal case.

    Returns:
        A dict with seven keys, always the same seven:
            verdict          — "good deal" | "fair" | "overpriced" | "unknown"
            comparable_count — int, how many listings the verdict rests on
            median_price     — float or None
            min_price        — float or None
            max_price        — float or None
            delta_vs_median  — float or None, this price minus that median
            summary          — str, one readable sentence naming the numbers

    When it has nothing: fewer than three comparables gives the same seven
    keys with verdict "unknown", the four price fields None, the real
    comparable count, and a summary saying why. The shape never changes, so
    agent.py can read result["verdict"] without guarding for the key.

    Comparables are listings in the same category sharing at least one style
    tag, excluding the item itself; if that is fewer than three, it widens to
    the category alone.

    Test it from a terminal:
        python -c "from tools import compare_prices; from utils.data_loader import load_listings; print(compare_prices(load_listings()[0]))"
    """
    if not isinstance(item, dict) or item.get("price") is None:
        return _unknown_price_check(0, "No item to price-check.")

    pool = load_listings() if listings is None else listings
    item_id = item.get("id")
    category = item.get("category")
    tags = set(item.get("style_tags") or [])

    others = [
        other for other in pool
        if other.get("id") != item_id
        and other.get("category") == category
        and other.get("price") is not None
    ]
    comparables = [o for o in others if tags & set(o.get("style_tags") or [])]
    basis = "same category and a shared style tag"
    if len(comparables) < _MIN_COMPARABLES:
        comparables = others
        basis = "same category"

    prices = sorted(float(o["price"]) for o in comparables)
    if len(prices) < _MIN_COMPARABLES:
        return _unknown_price_check(
            len(prices),
            f"Only {len(prices)} comparable "
            f"{'listing' if len(prices) == 1 else 'listings'} in the data for "
            f"{category or 'this category'}, which is too few to judge a "
            f"price against.",
        )

    median = round(statistics.median(prices), 2)
    price = round(float(item["price"]), 2)
    delta = round(price - median, 2)

    if price <= median * _GOOD_DEAL_AT:
        verdict = "good deal"
    elif price <= median * _FAIR_UP_TO:
        verdict = "fair"
    else:
        verdict = "overpriced"

    # "is a good deal" reads properly where "is overpriced" does not take an
    # article. The verdict string itself stays bare, because the loop compares
    # against it.
    phrase = f"a {verdict}" if verdict == "good deal" else verdict
    if delta == 0:
        gap = f"exactly at the ${median:.2f} median"
    else:
        direction = "below" if delta < 0 else "above"
        gap = f"${abs(delta):.2f} {direction} the ${median:.2f} median"

    summary = (
        f"${price:.2f} is {phrase} — {gap} of {len(prices)} comparable "
        f"listings (${min(prices):.2f}–${max(prices):.2f}, {basis})."
    )

    return {
        "verdict": verdict,
        "comparable_count": len(prices),
        "median_price": median,
        "min_price": min(prices),
        "max_price": max(prices),
        "delta_vs_median": delta,
        "summary": summary,
    }
