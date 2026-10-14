#!/usr/bin/env python3
"""
Does the search really miss one reasonable phrasing in five? ← UNIT 4

Criterion 1's target is 4 of 5 rather than 5 of 5, and the reason written down
in criteria.md before any results existed was this:

    "`tee` finds the graphic tees but `t-shirt` scores zero against the same
     items, and `jumper` finds nothing where `sweatshirt` finds three ... I
     expect roughly one query in five that a human would call reasonable to
     score zero and route to the empty-search branch instead."

That is a claim about the data and the tokeniser, not about the model, so it
can be measured exactly and for free — `search_listings` makes no model call
and is deterministic. This file measures it.

It is a diagnostic, not one of the five criteria. It exists because criterion
1's *number* rests on this claim, and a target whose justification goes
unchecked is a guess with a decimal point on it.

Each pair below is a listing that exists in the data, phrased the way the
seller titled it and phrased the way somebody else might reasonably ask for
the same garment.

    python probe_synonyms.py
"""

import config  # noqa: F401 — .env load and the Windows console fix
from agent import parse_query
from tools import search_listings

# (what a seller calls it, what a reasonable person might call it, the id they
#  should both be looking for)
PAIRS = [
    ("graphic tee",        "graphic t-shirt",      "lst_006"),
    ("sweatshirt",         "jumper",               "lst_012"),
    ("platform sneakers",  "platform trainers",    "lst_019"),
    ("corduroy pants",     "corduroy trousers",    "lst_005"),
    ("slip dress",         "cami dress",           "lst_013"),
    ("windbreaker",        "shell jacket",         "lst_010"),
    ("knit cardigan",      "cardi",                "lst_008"),
    ("mesh long-sleeve",   "fishnet top",          "lst_017"),
    ("chelsea boots",      "ankle boots",          "lst_028"),
    ("bucket hat",         "fisherman hat",        "lst_034"),
    ("shacket",            "overshirt",            "lst_032"),
    ("biker shorts",       "cycling shorts",       "lst_026"),
    ("denim shorts",       "jean shorts",          "lst_016"),
    ("leather bomber",     "leather flight jacket","lst_022"),
    ("mini shoulder bag",  "small handbag",        "lst_039"),
]


def finds(query: str, wanted: str) -> tuple[int, bool]:
    """How many results, and whether the intended listing was among them."""
    parsed = parse_query(query)
    results = search_listings(
        parsed["description"], parsed["size"], parsed["max_price"]
    )
    return len(results), any(r["id"] == wanted for r in results)


def main() -> None:
    print("Seller's wording vs. a reasonable alternative, same garment.\n")
    print(f"{'wanted':<9}{'seller phrasing':<22}{'hits':>5}{'  found':<9}"
          f"{'alternative':<24}{'hits':>5}  found")
    print("-" * 86)

    misses = 0
    for seller, other, wanted in PAIRS:
        n_a, hit_a = finds(seller, wanted)
        n_b, hit_b = finds(other, wanted)
        if not hit_b:
            misses += 1
        print(
            f"{wanted:<9}{seller:<22}{n_a:>5}{'  yes' if hit_a else '  NO':<9}"
            f"{other:<24}{n_b:>5}{'  yes' if hit_b else '  NO'}"
        )

    total = len(PAIRS)
    print(
        f"\n{misses} of {total} reasonable alternative phrasings failed to find "
        f"the garment\nthe seller's own wording finds — that is "
        f"{misses / total:.0%}, against the 20% that\ncriterion 1's 4-of-5 "
        f"target was set on."
    )
    print(
        "\nA phrasing that returns hits but not the intended garment is still a\n"
        "miss for the person who asked: they get styled an item they did not\n"
        "ask about, which no criterion currently catches."
    )


if __name__ == "__main__":
    main()
