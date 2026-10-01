# Acceptance criteria — FitFindr

Five criteria that say what "working" means for this agent, written in unit 3
**before** any results existed.

An acceptance criterion names a target: a number, a count, a rate, or something
a person could plainly observe. *"The agent handles errors"* is an opinion.
*"When search returns nothing, the agent stops before calling the second tool,
in 5 of 5 tries"* is a criterion.

> Missing your own targets next unit costs you nothing. Setting a target so
> easy you can't miss it does.

Criteria 1 and 2 were given. Criteria 3, 4 and 5 are mine.

---

## 1. A matching query completes all three tools

Given a query that matches at least one listing, the agent completes all three
tool calls and returns a fit card — in at least 4 of 5 tries.

**Why this target:**

4 of 5 and not 5 of 5 because the weak link is my own search, not the model.
`search_listings` is a plain keyword overlap score over title, style tags,
category, colors and description — there is no stemming beyond stripping a
trailing `s`, and no synonyms at all. So `tee` finds the graphic tees but
`t-shirt` scores zero against the same items, and `jumper` finds nothing where
`sweatshirt` finds three. Whether a given phrasing matches is a property of the
40 rows in `listings.json`, not of the agent, and I expect roughly one query in
five that a human would call reasonable to score zero and route to the
empty-search branch instead. The remaining risk is the two model calls: the
free tier gives 15 requests a minute and one run spends two, so a fifth
consecutive try can be paced or pushed back. `generate()` retries five times
with the delay the service asks for, which should absorb it, but I am not
willing to promise 5 of 5 on a path that depends on someone else's rate
limiter.

---

## 2. An impossible query stops before the second tool

Given a query that matches no listings, the agent stops before calling
`suggest_outfit` and returns a message naming what to change — 5 of 5 tries.

**Why this target:**

5 of 5 is right here, where it was not in criterion 1, because this path is
entirely deterministic and makes no model call. It is one `if` on the length of
a list that `search_listings` is specified to always return, reached by a
parser that is pure regex. Nothing in it can vary between tries: the same query
produces the same parse, the same filter, the same empty list, and the same
branch. If this ever comes out at 4 of 5 the cause is not variance, it is a
genuine defect — most likely `search_listings` returning `None` or raising on
some input instead of returning `[]`, which is exactly the failure this
criterion exists to catch. A flaky result here would be information, so I want
the target set where any failure at all is visible.

---

## 3. The item the search found is the item the next tool received

For 5 different matching queries, `session["selected_item"]["id"]` is identical
to the `id` of the listing dict that was passed into `suggest_outfit`, and that
same `id` appears in `session["search_results"]` — 5 of 5 tries. Checked by
reading the `--trace` output, where the selected item's id is recorded on the
`select_item` step and again on the `suggest_outfit` step: the two ids must be
the same string, and the fit card's named item must be that listing's title.

**Why this target:**

5 of 5, because an id is a string either equal to another string or not, and
there is no model in the comparison. Identity is the one thing in this agent I
can check exactly, so I should check it exactly and refuse myself any margin.
I chose `id` rather than `title` as the thing to compare because titles are not
unique in principle and would let a near-miss pass — two listings could share
a title where they cannot share an `id`. I added the third clause — that the id
also appears in `search_results` — because the first two clauses alone would
pass if the loop wrote the same wrong item to both places, which is precisely
what a state bug looks like. The real risk this guards against is my own
second branch: candidate rejection on an overpriced verdict advances an index,
and an off-by-one there would style candidate *n* while having written
candidate *n+1* into the session. That bug would produce a perfectly plausible
outfit for the wrong garment and nothing in the user-facing output would look
wrong, which is why it needs a criterion rather than a glance.

---

## 4. The fit card names the item, its price and its platform, every time

Across 5 fit cards generated for 5 different items, every card (5 of 5)
contains the item's price as a number and its platform name, and names the item
or its category in the first sentence. Separately, the 5 cards must have 5
distinct opening sentences, and each card must be between 2 and 4 sentences and
under 400 characters.

**Why this target:**

The model is at temperature 0.9, so I cannot ask for particular words and I am
not trying to. What I can require is that certain facts are present and that
the length is postable, both of which survive any amount of rewording. 5 of 5
on the facts is strict on purpose: the price and the platform are the two
things that make the card useful to someone deciding whether to buy, and
they are in the prompt every time, so a card missing one means my prompt is
losing them rather than the model being creative. I expect this to be the
criterion most at risk, and the reason is in my own data notes: 32 of the 40
listings have `brand` set to `None`, so any sentence I ask for that leans on
the brand will come out as a fragment. The distinct-openings clause is there
because the failure I would actually mind is a template — five cards opening
"Just found the perfect..." is a mail merge, not a caption, and the whole
reason temperature is above zero is to avoid that. I set the ceiling at 400
characters and 4 sentences because a caption longer than that is a product
description, and the tool's whole purpose is to produce something a person
would post.

---

## 5. A stated price ceiling is never exceeded, and the empty-search message is actionable

Two parts, both observable. **(a)** For 5 queries that each name a price
ceiling, no listing in `session["search_results"]` has a `price` above that
ceiling — 5 of 5 tries, zero violations in total across all results returned,
not just the selected one. **(b)** For 3 queries that match nothing, the
message in `session["error"]` names at least one specific constraint from the
parsed query with its value — the price ceiling, the size, or the keywords it
searched for — in 3 of 3 tries. "No results" or "Try a different search" fails
this.

**Why this target:**

Part (a) is zero tolerance because the filter is a single `<=` on a float that
is already parsed, and returning something over the ceiling is not a near miss
— it is the agent telling a user an item is in budget when it is not, which is
the one failure here that could cost someone money. I am checking every result
rather than just the selected item because the ceiling is a property of the
search, and a violation sitting at rank four is the same bug as one at rank one,
just better hidden; it would surface the moment the second branch rejects the
first three candidates. The reason I am not confident this is free is the parse,
not the filter: `under $30`, `below 30`, `$30 or less` and `max 30` are four
regexes, and a phrasing none of them catch yields `max_price = None` and a
search with no ceiling at all — silently, which is the same failure mode the
project brief warns about with PowerShell and double quotes.

Part (b) is 3 of 3 and it is deliberately the hardest thing on this page to
satisfy, because it is a judgement I am committing to in advance. The brief is
explicit that "No results" is not the message, and the test is whether a person
who knows nothing about my code could read it and know what to type next. The
only way to pass is for the message to quote the constraints actually applied —
"nothing under $5 in size XXS; I searched for: designer, ballgown" tells the
user which of three things to loosen, where "no results" tells them to give up.
I set this at 3 rather than 5 queries only because I have three genuinely
different empty cases to exercise — price too low, size not stocked, keywords
absent from the data — and a fourth would be a repeat rather than a new test.

---

<!-- ─────────────────────────────────────────────────────────────────────────
     UNIT 4 — read this before you change anything above.

     If a criterion turns out to be BROKEN rather than merely unmet, you can
     revise it, and that earns credit. But never delete or edit the original
     line. Add the revision underneath it, like this:

         ## 4. Something about the fit card

         The fit card is different every time.

         **Why this target:** ...

         > **Revised in unit 4:** For 5 different items, the 5 fit cards share
         > no opening sentence.
         >
         > **Why revised:** "different" wasn't checkable — two cards that
         > differed by one word still counted. The new version is something I
         > can actually score.

     That's a revision because the criterion couldn't be MEASURED.

     Lowering a target because you missed it is not a revision, and it costs
     you the point:

         ✗ "I said the empty search stops it 5 of 5 times, but I got 3 of 5,
            so 3 of 5 is more realistic."

     A number you missed stays where it is, gets diagnosed, and gets a fix
     attempted. That's where the points are.
     ───────────────────────────────────────────────────────────────────────── -->
