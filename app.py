#!/usr/bin/env python3
"""
FitFindr — command line.

    python app.py ask 'vintage graphic tee under $30, size M'
    python app.py ask                     keep asking until you quit
    python app.py ask --empty-wardrobe    run as a user with nothing saved
    python app.py ask --remember          style against your saved wardrobe,
                                          then add the find to it
    python app.py listings                browse the data  (Milestone 1)
    python app.py fields                  what fields a listing has
    python app.py examples                queries worth trying, including a dud
    python app.py wardrobe                what's in your saved wardrobe
    python app.py forget                  clear the saved wardrobe

Add --trace to any `ask` to print the loop step by step.

⚠️ Quote your query with SINGLE quotes. In PowerShell, "under $30" in double
quotes silently becomes "under " — PowerShell reads $30 as a variable and
substitutes nothing, so you search with no price ceiling and get no error
telling you why. Single quotes are literal in PowerShell, bash and zsh alike.
"""

import argparse
import sys

import config

# Every query here except the last one has something real to find in
# data/listings.json. If you add your own, check it against the data first — a
# query that finds nothing because the item doesn't exist looks exactly like a
# search tool that's broken.
EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "silk slip dress in midi length under $40",
    "platform sneakers size 8",
    "denim jacket under $50",
    "designer ballgown size XXS under $5",   # matches nothing, on purpose
]


def cmd_fields(args):
    """Milestone 1 — you can't filter on a field that isn't there."""
    from utils.data_loader import load_listings, get_example_wardrobe

    listing = load_listings()[0]
    print("A listing has these fields:\n")
    for key, value in listing.items():
        shown = str(value)
        if len(shown) > 58:
            shown = shown[:58] + "…"
        print(f"  {key:<14} {type(value).__name__:<6} {shown}")

    item = get_example_wardrobe()["items"][0]
    print("\nA wardrobe item has these fields:\n")
    for key, value in item.items():
        shown = str(value)
        if len(shown) > 58:
            shown = shown[:58] + "…"
        print(f"  {key:<14} {type(value).__name__:<6} {shown}")

    print(
        "\nThese are what search_listings can filter on. Read a few whole "
        "listings\nwith `python app.py listings` before you write it."
    )


def cmd_listings(args):
    """Milestone 1 — read the data before you write tools against it."""
    from utils.data_loader import load_listings

    listings = load_listings()

    if args.full:
        import json
        for listing in listings[: args.n]:
            print(json.dumps(listing, indent=2))
            print()
        return

    print(f"{len(listings)} listings.\n")
    print(f"{'id':<6}{'price':>8}  {'size':<22}{'platform':<11}title")
    print("-" * 92)
    for listing in listings[: args.n]:
        print(
            f"{str(listing['id']):<6}"
            f"{listing['price']:>8.2f}  "
            f"{str(listing['size']):<22}"
            f"{listing['platform']:<11}"
            f"{listing['title'][:38]}"
        )
    if len(listings) > args.n:
        print(f"\n… {len(listings) - args.n} more. Use -n {len(listings)} to see them all.")
    print("\nRead five or six all the way through: python app.py listings --full -n 6")


def cmd_examples(args):
    print("Queries worth trying:\n")
    for query in EXAMPLE_QUERIES[:-1]:
        print(f"  python app.py ask '{query}'")
    print(f"\nAnd one the data cannot match — this is the empty-search branch:\n")
    print(f"  python app.py ask '{EXAMPLE_QUERIES[-1]}'")
    print(
        "\nSingle quotes on purpose. In PowerShell a query in \"double quotes\"\n"
        "loses the $30 — it gets read as a variable — and you search with no\n"
        "price ceiling, with nothing to tell you it happened."
    )


def _ask_one(query, wardrobe, use_trace):
    from agent import run_agent
    import trace as trace_module

    if use_trace:
        trace_module.start_trace()

    session = run_agent(query, wardrobe)

    print()
    if session["error"]:
        print(f"  {session['error']}")
    else:
        item = session["selected_item"] or {}
        price = item.get("price")
        shown = f"{price:.0f}" if isinstance(price, float) and price == int(price) else price
        print(f"  Found:    {item.get('title')} — ${shown} on {item.get('platform')}")
        if session.get("price_check"):
            print(f"  Price:    {session['price_check']['summary']}")
        if session.get("rejected"):
            print(
                f"  Skipped:  {len(session['rejected'])} overpriced match"
                f"{'' if len(session['rejected']) == 1 else 'es'} ranked above it"
            )
        if session.get("price_warning"):
            print(f"  Warning:  {session['price_warning']}")
        print()
        print(f"  Outfit:   {session['outfit_suggestion']}")
        print()
        print(f"  Fit card: {session['fit_card']}")
    print()

    if use_trace:
        text = trace_module.get_trace()
        if not text:
            print(
                "  (--trace printed nothing. You haven't added trace.step() calls to\n"
                "   run_agent() yet — that's unit 4, Milestone 2.)\n"
            )
    return session


def _load_wardrobe(args):
    """
    Which wardrobe this run styles against.

    --empty-wardrobe wins over everything, because it exists to force the
    empty path. --memory and --remember both read the saved wardrobe, which
    falls back to the example one the first time. Otherwise it's the example.
    """
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
    from utils import style_memory

    if args.empty_wardrobe:
        print("(running with an empty wardrobe)")
        return get_empty_wardrobe()

    if args.memory or args.remember:
        wardrobe = style_memory.load_wardrobe()
        where = "saved" if style_memory.has_memory() else "example (nothing saved yet)"
        print(f"(styling against your {where} wardrobe — {len(wardrobe['items'])} items)")
        return wardrobe

    return get_example_wardrobe()


def cmd_ask(args):
    import generate
    from utils import style_memory

    wardrobe = _load_wardrobe(args)

    def run(query):
        session = _ask_one(query, wardrobe, args.trace)
        # Only a run that actually chose something has anything to remember.
        if args.remember and session.get("selected_item"):
            saved, added = style_memory.remember_item(session["selected_item"])
            title = session["selected_item"]["title"]
            if added:
                print(f"  Remembered: {title} — your wardrobe now has {len(saved['items'])} items.\n")
            else:
                print(f"  Already in your wardrobe: {title}.\n")
            # So a follow-up query in the same interactive session sees it.
            wardrobe["items"] = saved["items"]
        return session

    try:
        if args.query:
            run(args.query)
        else:
            print("Ask for something, or press Enter on an empty line to quit.\n")
            while True:
                try:
                    query = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not query:
                    break
                run(query)
    finally:
        print(generate.usage())


def cmd_wardrobe(args):
    """What style memory currently holds. (Stretch feature.)"""
    from utils import style_memory

    if not style_memory.has_memory():
        print(
            "Nothing saved yet, so runs style against the example wardrobe.\n"
            "Save a find with: python app.py ask '<query>' --remember"
        )
        return

    wardrobe = style_memory.load_wardrobe()
    print(f"{len(wardrobe['items'])} items in {style_memory.MEMORY_PATH.name}:\n")
    for item in wardrobe["items"]:
        notes = f"  — {item['notes']}" if item.get("notes") else ""
        print(f"  {item['id']:<14}{item['category']:<13}{item['name']}{notes}")


def cmd_forget(args):
    """Clear style memory. (Stretch feature.)"""
    from utils import style_memory

    if style_memory.forget_all():
        print("Saved wardrobe deleted. Runs will use the example wardrobe again.")
    else:
        print("Nothing to forget — no wardrobe was saved.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="FitFindr",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fields = sub.add_parser("fields", help="what fields the data has")
    p_fields.set_defaults(func=cmd_fields)

    p_list = sub.add_parser("listings", help="browse the listings data")
    p_list.add_argument("-n", type=int, default=15, help="how many to show")
    p_list.add_argument("--full", action="store_true", help="print whole records")
    p_list.set_defaults(func=cmd_listings)

    p_ex = sub.add_parser("examples", help="queries worth trying")
    p_ex.set_defaults(func=cmd_examples)

    p_ask = sub.add_parser("ask", help="run the agent")
    p_ask.add_argument("query", nargs="?")
    p_ask.add_argument("--trace", action="store_true", help="print the loop step by step")
    p_ask.add_argument(
        "--empty-wardrobe",
        action="store_true",
        help="run as a user with nothing saved — one of unit 4's failure modes",
    )
    p_ask.add_argument(
        "--memory",
        action="store_true",
        help="style against the saved wardrobe instead of the example one",
    )
    p_ask.add_argument(
        "--remember",
        action="store_true",
        help="use the saved wardrobe, then add this find to it",
    )
    p_ask.set_defaults(func=cmd_ask)

    p_wardrobe = sub.add_parser("wardrobe", help="what's in your saved wardrobe")
    p_wardrobe.set_defaults(func=cmd_wardrobe)

    p_forget = sub.add_parser("forget", help="clear the saved wardrobe")
    p_forget.set_defaults(func=cmd_forget)

    return parser


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 — students read this, not a traceback
        print(f"\n{type(exc).__name__}: {exc}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
