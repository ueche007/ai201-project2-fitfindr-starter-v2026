"""
The runs my test needs. Unit 4, Milestone 3.

Each of my five criteria needs something run against it. This file is me
working that out and writing it down.

`run_eval.py` runs everything in here five times, because my criteria are
written out of five, and `score.py` then checks the criteria against what came
back.

─────────────────────────────────────────────────────────────────────────────
HOW THESE SCENARIOS LINE UP WITH MY FIVE CRITERIA

Criteria 1, 3, 4 and 5(a) all need *several different queries that match*
rather than one query run several times:

    1    "the agent completes all three tool calls and returns a fit card"
    3    "for 5 different matching queries, the ids agree"
    4    "across 5 fit cards generated for 5 different items"
    5(a) "for 5 queries that each name a price ceiling"

So I use one set of five queries for all four, and I built the set to satisfy
every one of those at the same time. Each query names a price limit (that's
5a), each one actually matches something (criterion 1 needs that to even
start), and the five of them pick five *different* items in five different
categories (that's 4). That isn't luck -- I checked which item each query picks
before I wrote them down here, because `search_listings` and `compare_prices`
give the same answer every time, so I could work it out without spending a
single model call.

Two of the five I picked for the path they take, not for the item:

    levis 501 jeans      candidate 1 comes out overpriced and gets rejected, so
                         the loop goes round again. Criterion 3 is about
                         exactly this path -- the thing it says it's watching
                         for is an off-by-one that would style one candidate
                         while writing a different one into the session, and a
                         query that never rejects anything can't catch that.

    platform mary janes  every candidate comes out overpriced, so the `else`
                         part of my loop runs and it takes the top match anyway
                         with a warning. This is the only scenario that gets
                         anywhere near that code.

One "try" means one full pass through a criterion's whole set. So try 3 of
criterion 4 is my third pass over all five items, and it only passes if all
five cards in that pass were good. Five passes over five queries is 25 runs,
not 5. The repeating is what shows me where the model varies; the set of five
is what the criterion is actually asking about.

Criterion 2 is one impossible query, five times over. That path is just a
regular expression and an `if`, so nothing about it can change between tries,
which is the whole reason I set that target at 5 of 5.

Criterion 5(b) needs three *different kinds* of empty, not three empty queries:
a price limit nothing can meet, a size nothing is stocked in, and words that
just aren't in my data. Those three hit the three different branches of
`_no_results_message`, which is what the criterion is really about.
─────────────────────────────────────────────────────────────────────────────

`criteria` is the list of criteria a scenario feeds into. `criterion` is the
single number run_eval.py labels the row with. `note` is why I put it in.
"""

SCENARIOS = [
    # ── The five matching queries: criteria 1, 3, 4 and 5(a) ──────────────
    {
        "name": "tops — graphic tee",
        "query": "vintage graphic tee under $30",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_033",
        "note": "My unit 3 happy path, left exactly as it was so this unit's "
                "numbers can be compared with last unit's sample run.",
    },
    {
        "name": "outerwear — track jacket, with a size filter",
        "query": "90s track jacket in size M under $50",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_004",
        "note": "The only matching scenario that also has a size in it, so "
                "the price-then-size parsing order gets tested on a query "
                "that works.",
    },
    {
        "name": "bottoms — jeans, rejects one candidate first",
        "query": "levis 501 jeans under $40",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_037",
        "note": "Candidate 1 is overpriced and gets rejected, so the loop "
                "goes round again. This is the path where the off-by-one that "
                "criterion 3 is worried about would happen.",
    },
    {
        "name": "shoes — mary janes, every candidate overpriced",
        "query": "platform mary janes size US 7 under $60",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_009",
        "note": "Every candidate is overpriced, so my loop's else clause "
                "takes the top match anyway and warns about the price. "
                "Nothing else in my test reaches that code.",
    },
    {
        "name": "accessories — shoulder bag",
        "query": "mini shoulder bag under $40",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_039",
        "note": "My fifth different category. Criterion 4 wants five "
                "different items, and a bag is about as far from a t-shirt as "
                "this data gets.",
    },

    # ── Criterion 2: the empty-search branch ──────────────────────────────
    {
        "name": "impossible query stops before tool 2",
        "query": "designer ballgown size XXS under $5",
        "wardrobe": "example",
        "criterion": 2,
        "criteria": [2],
        "expect_item": None,
        "note": "The dud query from unit 3, unchanged. It has a price limit, "
                "a size and words that don't match, all at once.",
    },

    # ── Criterion 5(b): three different kinds of empty ────────────────────
    {
        "name": "empty — ceiling nothing can meet",
        "query": "vintage denim jacket under $5",
        "wardrobe": "example",
        "criterion": 5,
        "criteria": [5],
        "expect_item": None,
        "note": "Words that match plenty of things, with a $5 limit nothing "
                "can meet. The message has to say the $5 out loud, because "
                "the price is the one thing worth changing here.",
    },
    {
        "name": "empty — size nothing is stocked in",
        "query": "graphic tee in size XXS",
        "wardrobe": "example",
        "criterion": 5,
        "criteria": [5],
        "expect_item": None,
        "note": "Words that match, with a size nothing is stocked in. The "
                "message has to say the size out loud.",
    },
    {
        "name": "empty — words not in the data",
        "query": "sequined ballgown",
        "wardrobe": "example",
        "criterion": 5,
        "criteria": [5],
        "expect_item": None,
        "note": "No price limit and no size, so the only thing the message "
                "can repeat back is the words I searched for. This is the "
                "hardest of the three to make useful, and it's why I wrote "
                "5(b) the way I did.",
    },

    # ── Diagnostic: one of the three failure modes, not one of the five ───
    {
        "name": "empty wardrobe",
        "query": "denim jacket under $50",
        "wardrobe": "empty",
        "criterion": None,
        "criteria": [],
        "expect_item": "lst_007",
        "note": "The empty wardrobe failure from Milestone 2, run five times "
                "so I've actually tested it instead of trying it once. Not "
                "one of my five criteria.",
    },
]

WARDROBES = ("example", "empty")


def validate() -> list[str]:
    """Complain about anything malformed, before a long run rather than during."""
    problems = []
    for i, scenario in enumerate(SCENARIOS, 1):
        if not scenario.get("query", "").strip():
            problems.append(f"scenario {i} has no query")
        if scenario.get("wardrobe") not in WARDROBES:
            problems.append(
                f"scenario {i} has wardrobe {scenario.get('wardrobe')!r} — "
                f"it should be one of {WARDROBES}"
            )
        for number in scenario.get("criteria", []):
            if number not in (1, 2, 3, 4, 5):
                problems.append(
                    f"scenario {i} says it tests criterion {number!r}, which "
                    f"isn't one of the five in criteria.md"
                )
    return problems
