#!/usr/bin/env python3
"""
Does my search really miss one reasonable phrasing in five? Unit 4.

My criterion 1 target is 4 of 5 instead of 5 of 5, and the reason I wrote down
in criteria.md, before I had any results, was this:

    "`tee` finds the graphic tees but `t-shirt` scores zero against the same
     items, and `jumper` finds nothing where `sweatshirt` finds three ... I
     expect roughly one query in five that a human would call reasonable to
     score zero and route to the empty-search branch instead."

That's a claim about my data and my word-splitting, not about the model, so I
can check it exactly and for free -- `search_listings` makes no model calls and
gives the same answer every time. This file checks it.

It's not one of my five criteria, it's a side check. I wrote it because the
*number* in criterion 1 rests on that claim, and a target whose reasoning I
never checked is just a guess with a decimal point on it.

Each pair below is a real item in my data, written the way the seller titled it
and the way somebody else might reasonably ask for the same thing.

    python probe_synonyms.py
"""

import config  # noqa: F401 — .env load and the Windows console fix
from agent import parse_query
from tools import search_listings

# (what the seller calls it, what a normal person might call it, and the id
#  they should both be finding)
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
    """How many results came back, and whether the item I wanted was one."""
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
        "\nA phrasing that gets results but not the item I wanted is still a\n"
        "miss for whoever asked -- they get styled something they never asked\n"
        "about, and none of my criteria catch that."
    )


if __name__ == "__main__":
    main()
