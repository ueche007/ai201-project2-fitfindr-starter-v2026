"""
My MCP server.

Unit 4, Milestone 1. Before this, my tools only existed inside my own program
and nothing else could reach them. MCP is an agreed-on shape you wrap a tool in
so anything that speaks the same protocol can call it -- my agent now, somebody
else's app later.

I only moved one tool, which is the point: with one tool over MCP and three
still as plain function calls, I can actually see where the line is. I picked
`search_listings` because it doesn't call the model, so nothing is slow and
nothing changes between runs while I'm figuring out the shape.

    python mcp_server.py        starts the server (it just sits there, that's right)
    python mcp_client.py        asks the server what it offers
"""

from mcp.server.fastmcp import FastMCP

from tools import search_listings as _search_listings_impl  # noqa: F401 — you'll use this below

# log_level="WARNING" keeps the server from printing an INFO line for every
# request. Without it your terminal fills with "Processing request of type
# CallToolRequest" and the output you actually care about scrolls away.
mcp = FastMCP("fitfindr", log_level="WARNING")


# ── The one tool I put on MCP ────────────────────────────────────────────────
#
# I wrote the description below for somebody whose agent will never see my
# tools.py. That meant writing down the things I had only been keeping in my
# head: what the units are, what types come back, and what happens when nothing
# matches. This description is the only instruction manual they get.


@mcp.tool()
def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search 40 secondhand clothing listings and return the ones that match a
    description written in plain words, best match first.

    Matching is just keyword overlap against the listing's title, style tags,
    category, brand, colours and description. There are no synonyms, so "tee"
    and "t-shirt" will not find each other. It gives the same answer every
    time for the same inputs.

    Args:
        description: Words describing the clothing you want, like "vintage
            graphic tee". Required. It needs at least one real word in it --
            something longer than one letter that isn't a word like "the" or
            "find" -- or there is nothing to match on and you get an empty
            list back.
        size: A size to filter by, or null to skip the size filter. The sizes
            here come in four kinds that don't compare to each other, and a
            listing only matches inside its own kind: letters ("XXS" through
            "XXXL", and ranges written like "S/M"), waist ("W30", "W30 L30"),
            US shoe ("US 8", "US 8.5"), or one-size. A plain number counts as
            a US shoe size if it's 16 or under and a waist measurement if it's
            bigger. Anything listed as One Size matches whatever you ask for.
        max_price: The most you want to spend, in whole dollars, and it counts
            as "or cheaper" -- 30 means $30.00 and under. Null to skip the
            price filter. Everything here costs between $12 and $75.

    Returns:
        A list of up to 10 listings, best match first, and cheaper first when
        two match equally well. Each one has eleven fields straight from my
        data -- id (text), title (text), description (text), category (text),
        style_tags (list of text), size (text), condition (text), price (a
        number, in dollars), colors (list of text), brand (text or null, and
        it's null on 32 of the 40 listings), platform (text) -- plus one I add
        called match_score (a number), which is the keyword score I ranked it
        on.

        If nothing matches you get an empty list. Not null, not an error, and
        it won't crash. An empty list is the normal answer when I have nothing
        that fits, so read it as "nothing in stock for this" and not as
        something having gone wrong.
    """
    return _search_listings_impl(description, size, max_price)


# The name that gets registered is the function name, so the block above
# registers "search_listings", which is exactly what call_tool asks for. That is
# also why the import at the top of this file renames the real version: if the
# registered function and the one it calls had the same name, the tool would
# just call itself forever.
#
# FastMCP works out the input types from the type hints, so the hints aren't
# optional here. `description: str` turns into a required string and
# `max_price: float | None = None` turns into an optional number.


if __name__ == "__main__":
    mcp.run()
