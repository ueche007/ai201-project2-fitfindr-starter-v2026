"""
Your MCP server. ← UNIT 4, MILESTONE 1

Right now your tools only exist inside your own program. Nothing else can reach
them. MCP is an agreed shape you wrap a tool in so that anything speaking the
same protocol can call it — your agent today, a different agent tomorrow,
someone else's app after that.

**You're moving one tool. Not three.** The point is to see the seam.
`search_listings` is the one to move: it doesn't call the model, so nothing is
slow and nothing changes between runs while you're learning the shape.

    python mcp_server.py        starts the server (it will just sit there — that's right)
    python mcp_client.py        asks the server what it offers

─────────────────────────────────────────────────────────────────────────────
TODO — register one tool.

Uncomment the block below and fill it in. Three things matter:

  1. **The name.** Exactly what your agent will ask for.

  2. **The description.** This is the part that isn't code and matters most.
     Write it before you look at the example. You are not writing it for your
     agent — you're writing it for an agent someone else builds, that will
     never see your implementation. That isn't hypothetical; it's what every
     MCP server on the registry is.

     Two things to get right: name units and types ("price" is ambiguous,
     "max_price, in whole dollars" isn't), and state the empty case. Last unit
     the empty case was on your spec sheet for your loop's benefit. Here it's
     part of a published contract.

  3. **The typed inputs.** These come straight from your Tool Inventory. If the
     types here don't match your README, one of the two is wrong — fix it.

Then point your agent at it. In `run_agent()`, swap the direct call:

    results = search_listings(description, size, max_price)

for the MCP one:

    from mcp_client import call_tool
    results = call_tool("search_listings", {
        "description": description,
        "size": size,
        "max_price": max_price,
    })

**What comes back should not change.** If it does, that difference is your
first clue about what your tool was really returning before.

🛑 Stop rule: if this isn't connecting after 40 minutes, stop. Keep your direct
call, and write down in your README exactly where it broke — the error text and
the last thing that worked. Then carry on to Milestone 2. Everything after this
works with a direct call, and **a documented failure earns the point in full.**
─────────────────────────────────────────────────────────────────────────────
"""

from mcp.server.fastmcp import FastMCP

from tools import search_listings as _search_listings_impl  # noqa: F401 — you'll use this below

# log_level="WARNING" keeps the server from printing an INFO line for every
# request. Without it your terminal fills with "Processing request of type
# CallToolRequest" and the output you actually care about scrolls away.
mcp = FastMCP("fitfindr", log_level="WARNING")


# ── The one tool exposed over MCP ─────────────────────────────────────────────
#
# Written for an agent that will never see tools.py: every unit, every type and
# the empty case are stated in the description itself, because the description
# is the only documentation a remote caller gets.


@mcp.tool()
def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search a fixed catalogue of 40 secondhand clothing listings and return the
    ones matching a plain-language description, ranked best match first.

    Matching is keyword overlap against the listing's title, style tags,
    category, brand, colours and description — there is no synonym expansion,
    so "tee" and "t-shirt" do not find each other. Scoring is deterministic:
    the same arguments always return the same list in the same order.

    Args:
        description: Free-text keywords for the garment wanted, e.g.
            "vintage graphic tee". Required, and must contain at least one word
            longer than one character that is not a stopword — otherwise there
            is no basis for a match and the result is empty.
        size: A size string to filter by, or null for no size filter. Sizes in
            this catalogue span four incompatible scales and a listing only
            matches inside its own scale: letter ("XXS" … "XXXL", and ranges
            written "S/M"), waist ("W30", "W30 L30"), US shoe ("US 8",
            "US 8.5"), or one-size. A bare number is read as a US shoe size at
            16 or below and a waist measurement above it. Any listing whose own
            size is One Size matches every request.
        max_price: An inclusive ceiling in whole US dollars — 30 means $30.00
            and under. Null for no price filter. Every price in this catalogue
            is between $12 and $75.

    Returns:
        A JSON array of at most 10 listing objects, highest match first and
        cheaper first among equal scores. Each object has eleven catalogue
        fields — id (str), title (str), description (str), category (str),
        style_tags (array of str), size (str), condition (str), price (number,
        US dollars), colors (array of str), brand (str or null — null on 32 of
        the 40 listings), platform (str) — plus match_score (number), the
        keyword score it was ranked on.

        When nothing matches, returns an empty array. It does not return null,
        it does not return an error, and it does not raise: an empty array is
        the normal, expected answer to a query this catalogue cannot satisfy,
        and a caller should treat it as "no stock for these constraints"
        rather than as a failure.
    """
    return _search_listings_impl(description, size, max_price)


# The registered name is the *function* name, so the block above registers
# "search_listings" — exactly what call_tool("search_listings", ...) asks for.
# That is also why the import at the top brings the real implementation in
# under an alias: without it the registered function and the one it calls would
# share a name, and the tool would call itself.
#
# FastMCP builds the input schema from the type hints, which is why they are not
# optional here. `description: str` becomes a required string;
# `max_price: float | None = None` becomes an optional number.


if __name__ == "__main__":
    mcp.run()
