"""
The runs my test needs. ← UNIT 4, MILESTONE 3

Each of the five criteria in criteria.md needs something run against it. This
file is that worked out, scenario by scenario.

`run_eval.py` runs everything here five times — five because the criteria are
written out of five — and `score.py` applies the criteria to what came back.

─────────────────────────────────────────────────────────────────────────────
HOW THE SCENARIOS MAP ONTO THE FIVE CRITERIA

Criteria 1, 3, 4 and 5(a) all need *several different matching queries* rather
than one query several times:

    1    "the agent completes all three tool calls and returns a fit card"
    3    "for 5 different matching queries, the ids agree"
    4    "across 5 fit cards generated for 5 different items"
    5(a) "for 5 queries that each name a price ceiling"

So one set of five queries serves all four, and the set is built to satisfy
every one of those clauses at once. Each query names a price ceiling (5a),
each matches at least one listing (1's precondition), and the five select five
*distinct* items in five distinct categories (4). That is not a coincidence —
the selections were checked against the data before the queries were written
down, because `search_listings` and `compare_prices` are both deterministic, so
which item each query selects is knowable in advance without spending a model
call.

Two of the five are chosen for the loop path they exercise, not for the item:

    levis 501 jeans      candidate 1 is judged overpriced and rejected, so the
                         loop goes round again. Criterion 3 exists for exactly
                         this path — its stated risk is an off-by-one that
                         would style candidate n while writing candidate n+1
                         into the session, and a query that never rejects
                         cannot catch that.

    platform mary janes  every candidate is judged overpriced, so the `else`
                         clause of the loop runs and the top match is taken
                         with a price warning. The only scenario that reaches
                         that code.

A "try" is one repetition of a criterion's whole set. So try 3 of criterion 4
means the third pass over all five items, and it passes only if all five cards
in that pass satisfied the criterion. Five repetitions of five queries is 25
runs, not 5 — the repetition is what exposes model variance, and the set is
what the criterion actually asks about.

Criterion 2 is one impossible query, five repetitions — the path is pure regex
and an `if`, so what varies between tries is nothing, which is the point of
the 5-of-5 target.

Criterion 5(b) needs three *different* kinds of empty, not three empty queries:
a ceiling nothing can meet, a size nothing is stocked in, and words that are
not in the data at all. Those three exercise the three different branches of
`_no_results_message`, which is what the criterion is really about.
─────────────────────────────────────────────────────────────────────────────

`criteria` is the list of criteria a scenario feeds. `criterion` stays as the
single number run_eval.py labels the row with. `note` is why the scenario is
in the set.
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
        "note": "The unit 3 happy path, kept unchanged so this unit's numbers "
                "are comparable with last unit's sample run.",
    },
    {
        "name": "outerwear — track jacket, with a size filter",
        "query": "90s track jacket in size M under $50",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_004",
        "note": "The only matching scenario that also parses a size, so the "
                "price-then-size parse order is exercised on the happy path.",
    },
    {
        "name": "bottoms — jeans, rejects one candidate first",
        "query": "levis 501 jeans under $40",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_037",
        "note": "Candidate 1 is overpriced and rejected, so the loop re-plans. "
                "This is the path criterion 3's off-by-one risk lives on.",
    },
    {
        "name": "shoes — mary janes, every candidate overpriced",
        "query": "platform mary janes size US 7 under $60",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_009",
        "note": "Every candidate is overpriced, so the loop's else clause takes "
                "the top match with a price warning. Nothing else reaches it.",
    },
    {
        "name": "accessories — shoulder bag",
        "query": "mini shoulder bag under $40",
        "wardrobe": "example",
        "criterion": 1,
        "criteria": [1, 3, 4, 5],
        "expect_item": "lst_039",
        "note": "Fifth distinct category. Criterion 4 wants five different "
                "items, and an accessory is the furthest thing from a tee.",
    },

    # ── Criterion 2: the empty-search branch ──────────────────────────────
    {
        "name": "impossible query stops before tool 2",
        "query": "designer ballgown size XXS under $5",
        "wardrobe": "example",
        "criterion": 2,
        "criteria": [2],
        "expect_item": None,
        "note": "The unit 3 dud, unchanged. All three constraints at once.",
    },

    # ── Criterion 5(b): three different kinds of empty ────────────────────
    {
        "name": "empty — ceiling nothing can meet",
        "query": "vintage denim jacket under $5",
        "wardrobe": "example",
        "criterion": 5,
        "criteria": [5],
        "expect_item": None,
        "note": "Keywords that match plenty; a $5 ceiling that nothing meets. "
                "The message has to name the ceiling, because the ceiling is "
                "the one thing worth loosening.",
    },
    {
        "name": "empty — size nothing is stocked in",
        "query": "graphic tee in size XXS",
        "wardrobe": "example",
        "criterion": 5,
        "criteria": [5],
        "expect_item": None,
        "note": "Keywords that match; a size no listing carries. The message "
                "has to name the size.",
    },
    {
        "name": "empty — words not in the data",
        "query": "sequined ballgown",
        "wardrobe": "example",
        "criterion": 5,
        "criteria": [5],
        "expect_item": None,
        "note": "No ceiling and no size, so the message has nothing to quote "
                "but the keywords. The hardest of the three to make "
                "actionable, and the reason 5(b) is written as it is.",
    },

    # ── Diagnostic: one of the three failure modes, not one of the five ───
    {
        "name": "empty wardrobe",
        "query": "denim jacket under $50",
        "wardrobe": "empty",
        "criterion": None,
        "criteria": [],
        "expect_item": "lst_007",
        "note": "Failure mode 2 from Milestone 2, run five times so it is "
                "tested rather than tried once. Not one of the five criteria.",
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
                    f"scenario {i} claims criterion {number!r}, which isn't "
                    f"one of the five in criteria.md"
                )
    return problems
