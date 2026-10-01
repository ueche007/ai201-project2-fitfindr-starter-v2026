# FitFindr

An agent that does the tedious part of thrifting: you say what you want in
plain language, and it searches listings, works out what the find would go with
from clothes you already own, and writes a caption you could actually post.

> **How to run this project: [RUNNING.md](RUNNING.md)**
>
> ```bash
> python test.py                                    # environment check
> python app.py ask 'vintage graphic tee under $30' # the agent
> ```

---

<!-- ═══════════════════════ UNIT 3 — THE BUILD ═══════════════════════ -->

## What This Does

A user types one plain-language request — `vintage graphic tee under $30, size M`
— and FitFindr turns it into a complete styling answer. It parses the price
ceiling and the size out of the sentence, searches 40 secondhand listings for
keyword matches, checks whether the one it picked is fairly priced against
comparable items, asks the model how that piece would work with clothes the user
already owns, and writes a short caption for the find. What comes back is three
things: the listing (title, price, platform), an outfit built from named pieces
in the user's wardrobe, and a postable fit card. When nothing in the data matches
the request, it stops after the search and says which part of the request to
loosen, rather than styling an item it never found.

### Stretch features in this submission

All three optional features are implemented, declared here before the build:

1. **A fourth tool** — `compare_prices`, which scores the found item against
   comparable listings and returns a verdict of good deal / fair / overpriced.
2. **A second branch** — the loop rejects an overpriced candidate and re-plans
   onto the next one, instead of accepting whatever the search ranked first.
3. **Style memory** — the wardrobe persists to `data/style_memory.json` between
   runs, so an item found in one run can be worn in the next.

---

## Tool Inventory

### `search_listings`

- **What it does:** Filters the listings dataset down to the items that match a
  plain-language description, and optionally a size and a price ceiling, then
  ranks what survives by keyword overlap. It is the only one of the four tools
  that does not call the model.
- **Inputs:**
  - `description` (`str`) — keywords describing the wanted item, e.g.
    `"vintage graphic tee"`. Required.
  - `size` (`str | None`) — a size string such as `"M"`, `"W30"` or `"8"`.
    `None` skips size filtering entirely.
  - `max_price` (`float | None`) — an inclusive price ceiling. `None` skips
    price filtering entirely.
- **Returns:** A `list[dict]` of whole listing dicts, highest keyword score
  first and cheaper first among ties, capped at `config.SEARCH_RESULT_LIMIT`
  (10). Every dict carries the eleven fields straight from `listings.json` —
  `id`, `title`, `description`, `category`, `style_tags` (`list[str]`), `size`,
  `condition`, `price` (`float`), `colors` (`list[str]`), `brand` (`str` or
  `None`), `platform` — plus one key this tool adds: `match_score` (`float`),
  the keyword score it was ranked on.
- **When it has nothing:** Returns `[]` — an empty list. Not `None`, not a
  string, and it does not raise. This is the value the loop's first branch
  tests, so it has to be one definite thing.

**Size matching rule.** Sizes in the data span four incompatible scales, so a
substring test is wrong: `"s" in "us 9"` is `True` and so is `"l" in "xl"`.
Both the request and the listing are classified into a family — letter
(`S`/`M`/`L`/`XL` and ranges like `S/M`), waist (`W27`…`W32`, `W30 L30`), shoe
(`US 7`…`US 9`), or one-size — and a listing matches only inside its own
family. Any `One Size*` listing matches every request. Letter ranges split on
`/` into a token set, so `S/M` satisfies a request for `S` or for `M`.
Parentheticals are stripped first, so `XL (oversized)` is just `XL`. A bare
number is read as a shoe size at 16 or below and a waist size above it.

### `suggest_outfit`

- **What it does:** Asks the model how one thrifted item would be worn, naming
  specific pieces from the user's wardrobe where it can.
- **Inputs:**
  - `new_item` (`dict`) — one listing dict, as returned by `search_listings`.
    Required.
  - `wardrobe` (`dict`) — a wardrobe dict with an `items` key holding a
    `list[dict]`; each item has `id`, `name`, `category`, `colors`,
    `style_tags`, `notes`. May be empty. Required.
- **Returns:** A non-empty `str` — one or two outfit ideas in prose, each naming
  the pieces it combines. With a stocked wardrobe the names are the user's own
  items, quoted from the `name` field.
- **When it has nothing:** Two separate nothing-cases, each with a decided
  answer. An **empty wardrobe** (`items == []`) returns general styling advice
  for the item — what to pair it with in the abstract — prefixed with a line
  saying the advice is general because no wardrobe is saved. It does not raise
  and does not return `""`. A **missing or non-dict `new_item`** returns the
  fixed string `"No item to style — search_listings returned nothing."`, because
  reaching this tool with no item means the loop's branch failed and the string
  should say so rather than hide it.

### `create_fit_card`

- **What it does:** Writes a short caption about the find, of the kind someone
  would actually post with a photo.
- **Inputs:**
  - `outfit` (`str`) — the outfit text from `suggest_outfit`. Required.
  - `new_item` (`dict`) — the same listing dict the outfit was built around.
    Required.
- **Returns:** A `str` of two to four sentences that names the item, states its
  price and its platform exactly once each, and describes the vibe. Written at
  `config.TEMPERATURE` (0.9), so the same item yields different wording run to
  run — that variation is the point of a caption, and criterion 4 is what keeps
  it inside acceptable bounds.
- **When it has nothing:** If `outfit` is empty, whitespace-only, or not a
  string, it returns the descriptive string `"No fit card — there was no outfit
  to write about."` and makes no model call. If `new_item` is missing or not a
  dict it returns `"No fit card — there was no item to write about."` Neither
  case raises.

### `compare_prices` *(stretch — fourth tool)*

- **What it does:** Works out whether one listing is fairly priced by comparing
  it against comparable listings in the same dataset.
- **Inputs:**
  - `item` (`dict`) — the listing dict to price-check. Required.
  - `listings` (`list[dict] | None`) — the pool to compare against. `None`
    loads the full dataset, which is the normal case.
- **Returns:** A `dict` with seven keys, always the same seven:
  - `verdict` (`str`) — one of `"good deal"`, `"fair"`, `"overpriced"`,
    `"unknown"`
  - `comparable_count` (`int`) — how many listings the verdict rests on
  - `median_price` (`float | None`) — median of the comparables
  - `min_price` (`float | None`) and `max_price` (`float | None`) — their range
  - `delta_vs_median` (`float | None`) — this item's price minus that median,
    rounded to 2dp
  - `summary` (`str`) — one sentence a person can read, naming the numbers
- **When it has nothing:** With fewer than three comparables there is no
  distribution worth a verdict, so it returns the same seven keys with
  `verdict` set to `"unknown"`, the four price fields set to `None`,
  `comparable_count` set to the real count (`0`, `1` or `2`), and a `summary`
  that says why no verdict was reached. Returning the same shape in every case
  is deliberate: the loop reads `result["verdict"]` without first having to
  check whether the dict it got back has that key.

**Comparables rule.** Same `category`, and at least one shared `style_tag`,
excluding the item itself. If that yields fewer than three, it widens to same
`category` alone. Thresholds against the comparable median: at or below 85% is
a `"good deal"`, up to 115% is `"fair"`, above that is `"overpriced"`.

---

## Planning Loop

**Branch rule (the required branch):**

> If `search_listings` returns an empty list, put a message in
> `session["error"]` naming which part of the request to loosen — the price
> ceiling, the size, or the keywords, whichever were actually applied — and
> return the session immediately, leaving `selected_item`,
> `outfit_suggestion` and `fit_card` as `None`. Otherwise, select a candidate
> from the results, write it to `session["selected_item"]`, and continue to
> `suggest_outfit`.

**Second branch rule (stretch):**

> For each candidate in the search results, in rank order: if
> `compare_prices` returns `verdict == "overpriced"`, reject that candidate,
> record the rejection in `session["rejected"]`, and go round the loop again
> with the next one. Otherwise accept it and stop looking. If every candidate
> is overpriced, accept the first one anyway and set
> `session["price_warning"]`, because a styled overpriced item is still a more
> useful answer than nothing.

**Where it lives:** `agent.py::run_agent`

**How the query is parsed:** Regex, in `agent.py::parse_query` — no model call.
The price ceiling is matched first and its matched span is removed from the
string, so `under $30` cannot afterwards be misread as `size 30`. The size is
matched next by the same method, and the keywords left over become the
description after a stopword list (`looking`, `for`, `a`, `in`, `size`, `want`,
`need`, `find`, `me`, `my`, `the`, `something`, `under`, `with`) is removed.
Regex over a model call because parsing is the one deterministic step in the
run, and a deterministic parser is the only reason criterion 5 can be checked
at all.

**What moves through the session, in order:**

| Step | Written | Read by the next step |
|---|---|---|
| 1 | `query` | `parse_query` |
| 2 | `parsed` — `description`, `size`, `max_price` | `search_listings` |
| 3 | `search_results` | the empty-search branch, then candidate selection |
| 4 | `price_check`, `rejected` | the overpriced branch |
| 5 | `selected_item` | `suggest_outfit`, then `create_fit_card` |
| 6 | `outfit_suggestion` | `create_fit_card` |
| 7 | `fit_card` | printed to the user |

No value is passed straight from one call into the next. Every tool result is
written into the session and read back out of it, which is what makes the
state visible to the trace and checkable by criterion 3.

---

## Sample Run

<!-- Filled in at Milestone 4 and Milestone 5. -->

---

## How I Used AI

<!-- Filled in at Milestone 6. -->

<!-- ═══════════════════════ UNIT 4 — THE TEST ═══════════════════════

     Don't fill these in during unit 3.
     ═══════════════════════════════════════════════════════════════════ -->

---

## Run Log — Before

<!-- Five criteria, five tries each, in this exact format.

     Five, because your criteria are written out of five. Mark each try PASS
     or FAIL, count the passes, and read that count against your target — a
     row targeting 4 of 5 with three PASS cells is MISSED (3/5).

     `python run_eval.py --label before` runs everything and writes the table
     into results/. Paste it here and fill in the verdicts. -->

| Criterion | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 1.  |  |  |  |  |  |  |  |
| 2.  |  |  |  |  |  |  |  |
| 3.  |  |  |  |  |  |  |  |
| 4.  |  |  |  |  |  |  |  |
| 5.  |  |  |  |  |  |  |  |

**Real output from one try**, pasted as text, naming the file and function
that produced it:

```

```

---

## Verdicts and Diagnoses

<!-- MET or MISSED per criterion against LAST UNIT's target, plus a sentence on
     how you decided.

     Then, for every miss: which of the four places it happened — a tool, the
     loop's branch, the session, or the model's output — AND the mechanism.

     Not a diagnosis:  "The fit card was bad."
     A diagnosis:      "The fit card criterion missed on 2 of 5 items. Both had
                        an empty brand field. My prompt puts the brand in the
                        first sentence, so the card opened with a blank and read
                        like a fragment. The tool worked; the prompt assumed a
                        field that isn't always there."

     Look for a pattern. Three misses on the same tool is one problem, not
     three. -->

| # | Criterion | Target | Verdict | How I decided |
|---|---|---|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |
| 4 |  |  |  |  |
| 5 |  |  |  |  |

**Diagnoses**



---

## Loop Trace

<!-- One full run, printed step by step, with the MCP call visible in it.

     `python app.py ask '...' --trace` once you've added the trace.step()
     calls in Milestone 2.

     Worth pasting BOTH the happy path and the empty-search path. The empty
     one should be visibly shorter, because it stops. If your two traces are
     the same length, your branch isn't working — and this is the fastest way
     anyone will ever find that out. -->

**Happy path**

```

```

**Empty search**

```

```

**On the MCP move:** <!-- what changed in your code, and whether anything
behaved differently afterwards. If the rewire didn't work, say exactly where it
broke — the error text and the last thing that worked. That earns the point in
full. -->



---

## The Improvement

<!-- What you changed, why your diagnosis pointed at it, and the after-run in
     the same table format. One change, measured properly.

     `python run_eval.py --label after` -->

**What I changed:**

**Which failure it was meant to fix:**

### Run Log — After

| Criterion | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 1.  |  |  |  |  |  |  |  |
| 2.  |  |  |  |  |  |  |  |
| 3.  |  |  |  |  |  |  |  |
| 4.  |  |  |  |  |  |  |  |
| 5.  |  |  |  |  |  |  |  |

**Did it help, and how do I know:**

<!-- If it made things worse, say that. Honestly reported, that earns full
     credit and is more interesting than one that worked. -->



---

## What's Still Broken

<!-- For each criterion still missed: what you'd do, and why you stopped where
     you did. "I ran out of time" is fine if it's true. Pretending nothing is
     left is not. -->



<!-- ═════════════════════════════════════════════════════════════════════

     SUBMISSION CHECKLIST — unit 3

       [ ] criteria.md has five numbered criteria, each with a target
       [ ] Each criterion has a reason underneath it
       [ ] All five unit 3 sections above have real content
       [ ] Tool Inventory: all three tools, inputs WITH TYPES, a specific
           return value, and the empty case
       [ ] Planning Loop names the branch rule and agent.py::run_agent
       [ ] Sample Run: one full query plus the three per-tool tests, as text
       [ ] At least four new commits
       [ ] Repository URL submitted — WRITE IT DOWN, you submit the same one
           next unit

     SUBMISSION CHECKLIST — unit 4

       [ ] mcp_server.py exists with one tool registered
           (or a written record of exactly where the rewire broke)
       [ ] Run Log — Before, five criteria, five tries each
       [ ] Real output pasted underneath, naming file and function
       [ ] A verdict on every criterion
       [ ] A diagnosis for every miss, naming a place AND a mechanism
       [ ] Loop Trace, with the MCP call visible in it
       [ ] All three failure modes triggered and handled
       [ ] One improvement, with Run Log — After in the same format
       [ ] What's Still Broken
       [ ] At least four new commits
       [ ] The SAME repository URL as last unit

     Do not delete and recreate this repository. Your commit history is what
     shows your criteria existed before your results did.
     ═════════════════════════════════════════════════════════════════════ -->

---

📖 **How to run this project: [RUNNING.md](RUNNING.md)**
