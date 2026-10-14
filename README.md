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

**Added in unit 4:** one stretch feature from that unit's list — **a second
improvement from the diagnosis, measured the same way as the first**. Declared
under [The Improvement](#the-improvement) before it was built. A second tool was
*not* moved onto MCP, and retry-with-looser-constraints was *not* added.

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
- **Reached over MCP since unit 4.** `agent.py` no longer imports this function.
  It is registered in `mcp_server.py` and called by name over stdio through
  `mcp_client.call_tool`; the implementation below is unchanged and still lives
  in `tools.py`. The inputs and types in this entry are what the published MCP
  schema is built from — `description` required string, `size` and `max_price`
  optional — and they needed no correction when the two were compared. Direct
  and MCP calls were diffed on the same arguments and return identical values,
  including `[]`. See [On the MCP move](#loop-trace).

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

Every block below is real terminal output, pasted as text.

### One full query, end to end

```
$ python app.py ask 'vintage graphic tee under $30, size M'

  Found:    Y2K Baby Tee — Butterfly Print — $18 on depop
  Price:    $18.00 is a good deal — $3.50 below the $21.50 median of 14 comparable listings ($15.00–$35.00, same category and a shared style tag).

  Outfit:   **Outfit 1**
Pair the Y2K Baby Tee — Butterfly Print with the baggy straight-leg jeans, dark wash and the chunky white sneakers. Finish with the brown leather belt. This combination plays with silhouette proportions by balancing the ultra-fitted baby tee with loose-fitting bottoms, keeping the color palette grounded with the dark denim.

**Outfit 2**
Layer the vintage black denim jacket (Slightly cropped) over the Y2K Baby Tee — Butterfly Print, paired with the wide-leg khaki trousers and the black combat boots (Lace-up, mid-ankle height). This look contrasts the soft, feminine butterfly graphic with rugged boots and structured trousers for an edgy Y2K street style.

  Fit card: Snagged this little butterfly tee for $18 and it's practically screaming early 2000s mall culture in the best way possible. Throw it on with some baggy dark denim to play with the proportions, or toughen up the sweet pastel graphic with a cropped jacket and heavy combat boots. It’s up on depop now if your rotation needs a heavy dose of nostalgia.

2 model calls this session, 686 prompt + 228 output tokens
```

### The same runner on a query the data cannot match

The branch fires: it stops after the search, and `fit_card` is never written.

```
$ python app.py ask 'designer ballgown size XXS under $5'

  Nothing in the 40 listings matches all of: keywords: designer, ballgown; price at or under $5; size XXS.
  To get results, raise the $5 ceiling, drop or widen the size filter (XXS), or use words closer to how a seller would title it — this data runs on terms like vintage, y2k, 90s, graphic tee, denim, oversized, grunge, linen.

0 model calls this session
```

### The second branch re-planning (stretch), with `--trace`

Two overpriced candidates rejected before a third is accepted. Note that the
step numbers make the branch visible: `compare_prices` runs three times and
`select_item` only once.

```
$ python app.py ask 'chunky knit cardigan' --trace
[1] parse_query
      in:  chunky knit cardigan
      out: description='chunky knit cardigan', size=None, max_price=None
[2] search_listings
      in:  description='chunky knit cardigan', size=None, max_price=None
      out: 3 items: Knit Cardigan — Chunky Brown, Vintage Knit Vest — Argyle Brown/Cream, Platform Sneakers — White Chunky Sole
[3] compare_prices
      in:  candidate 1 of 3: lst_008 at $35
      out: overpriced
      →    $35.00 is overpriced — $15.00 above the $20.00 median of 9 comparable listings ($16.00–$28.00, same category and a shared style tag).
[4] branch
      out: rejected lst_008
      →    overpriced — going round again with the next candidate
[5] compare_prices
      in:  candidate 2 of 3: lst_030 at $25
      out: overpriced
      →    $25.00 is overpriced — $4.00 above the $21.00 median of 11 comparable listings ($16.00–$35.00, same category and a shared style tag).
[6] branch
      out: rejected lst_030
      →    overpriced — going round again with the next candidate
[7] compare_prices
      in:  candidate 3 of 3: lst_019 at $48
      out: fair
      →    $48.00 is fair — $4.00 above the $44.00 median of 3 comparable listings ($20.00–$55.00, same category).
[8] select_item
      in:  candidate 3 of 3
      out: Platform Sneakers — White Chunky Sole ($48.0, poshmark)
      →    session['selected_item']['id'] = lst_019
[9] suggest_outfit
      in:  selected_item id = lst_019 (read back from session), wardrobe items = 10
      out: **Outfit 1** Pair the platform sneakers with the baggy straight-leg jeans, dark wash and the black cropped zip…
[10] create_fit_card
      in:  outfit = 526 chars, selected_item id = lst_019
      out: These stark white platform sneakers have that heavy-bottomed late-90s energy that makes baggy denim actually w…

  Found:    Platform Sneakers — White Chunky Sole — $48 on poshmark
  Price:    $48.00 is fair — $4.00 above the $44.00 median of 3 comparable listings ($20.00–$55.00, same category).
  Skipped:  2 overpriced matches ranked above it

  Outfit:   **Outfit 1**
Pair the platform sneakers with the baggy straight-leg jeans, dark wash and the black cropped zip hoodie. The cropped zip hoodie balances the heavy volume of the baggy denim, while the white chunky sole bridges the gap between the streetwear silhouette and the footwear. 

**Outfit 2**
Wear the platform sneakers with the wide-leg khaki trousers and the white ribbed tank top. The stark white sneakers echo the clean tank top to brighten up the earthy khaki, creating an effortless late-90s minimalist proportion.

  Fit card: These stark white platform sneakers have that heavy-bottomed late-90s energy that makes baggy denim actually work. I scored them on poshmark for $48 and immediately paired them with khaki trousers for an effortless, grounded silhouette.

0 model calls this session, 2 served from cache
```

### The four tools, tested one at a time

**1. `search_listings`** — the price ceiling holds across every result, and the
empty case is `[]`:

```
$ python -c "from tools import search_listings; [print(f\"{r['id']}  ${r['price']:<6} {r['size']:<8} score={r['match_score']}  {r['title']}\") for r in search_listings('graphic tee', max_price=30)]"
lst_006  $24.0   L        score=6.0  Graphic Tee — 2003 Tour Bootleg Style
lst_002  $18.0   S/M      score=5.0  Y2K Baby Tee — Butterfly Print
lst_033  $19.0   L        score=5.0  Vintage Band Tee — Faded Grey
lst_015  $26.0   L        score=3.0  Vintage Graphic Hoodie — Faded Black
lst_017  $15.0   S/M      score=2.0  Mesh Long-Sleeve Top — Black
lst_012  $20.0   XL (fits oversized) score=1.0  Oversized Crewneck Sweatshirt — Vintage Navy
lst_011  $27.0   W29      score=1.0  Low-Rise Cargo Pants — Khaki

empty case: []
```

**2. `suggest_outfit`** — names pieces from the wardrobe, as written:

```
$ python -c "from tools import suggest_outfit; from utils.data_loader import get_example_wardrobe, load_listings; print(suggest_outfit(load_listings()[1], get_example_wardrobe()))"
**Outfit 1**
Pair the Y2K Baby Tee — Butterfly Print with the baggy straight-leg jeans, dark wash and the chunky white sneakers. Finish with the brown leather belt. This combination plays with silhouette proportions by balancing the ultra-fitted baby tee with loose-fitting bottoms, keeping the color palette grounded with the dark denim.

**Outfit 2**
Layer the vintage black denim jacket (Slightly cropped) over the Y2K Baby Tee — Butterfly Print, paired with the wide-leg khaki trousers and the black combat boots (Lace-up, mid-ankle height). This look contrasts the soft, feminine butterfly graphic with rugged boots and structured trousers for an edgy Y2K street style.
```

**3. `create_fit_card`**:

```
$ python -c "from tools import create_fit_card; from utils.data_loader import load_listings; print(create_fit_card('Baby tee with baggy dark-wash jeans and chunky white sneakers.', load_listings()[1]))"
Found the absolute dreamiest Y2K butterfly baby tee, complete with lilac and pink graphics that scream early 2000s mall culture. I’m leaning all the way into the contrast by pairing it with heavy dark-wash denim and chunky white sneakers for that perfect heavy-top, loose-bottom silhouette. Snag this piece over on my depop right now for eighteen dollars before I change my mind and keep it.
```

**4. `compare_prices`** (stretch) — the same seven keys on a real verdict and on
the unknown path:

```
$ python -c "from tools import compare_prices; from utils.data_loader import load_listings; import json; print(json.dumps(compare_prices([l for l in load_listings() if l['id']==\"lst_022\"][0]), indent=2, ensure_ascii=False))"
{
  "verdict": "overpriced",
  "comparable_count": 7,
  "median_price": 40.0,
  "min_price": 27.0,
  "max_price": 52.0,
  "delta_vs_median": 35.0,
  "summary": "$75.00 is overpriced — $35.00 above the $40.00 median of 7 comparable listings ($27.00–$52.00, same category and a shared style tag)."
}

empty case: {"verdict": "unknown", "comparable_count": 0, "median_price": null, "min_price": null, "max_price": null, "delta_vs_median": null, "summary": "No item to price-check."}
```

### Two things worth recording from these runs

**The fit card wrote the price as words.** In the `create_fit_card` test above,
the caption ends "for eighteen dollars" rather than "$18". Criterion 4 requires
the price "as a number", so that try would score FAIL. It is in the prompt twice
as `$18`, and the model spelled it out anyway. I have left the criterion where
it is — diagnosing this is unit 4's job, and lowering a target to meet it is
not a revision.

**Keyword matching on the seller's description pulls in the wrong garments.**
`search_listings('graphic tee')` returns `lst_017` (a mesh top) and `lst_011`
(cargo pants) at the bottom of the ranking, because both descriptions mention
layering "under a graphic tee". Worse, `lst_012`'s description reads "no
graphics, clean" — and matches `graphic`, because a substring test cannot see a
negation. Both rank low enough that the loop never selects them, so this costs
nothing today. It is the most likely cause if criterion 1 misses next unit.

---

## How I Used AI

I built this with Claude Code (Opus) driving the implementation, in one
session, with me directing what to build and reviewing the output at each
milestone. The two moments below are the ones where what came back changed a
decision rather than just saving typing.

**Moment 1 — the size filter**

- *What I asked for:* Before writing `search_listings`, I asked for a survey of
  every distinct `size` value in `listings.json` and for the specific ways a
  naive size filter would go wrong against that data.
- *What came back:* 22 distinct size strings across four scales that do not
  compare — letter (`S`, `M`, `S/M`, `XL (oversized)`), waist (`W27`–`W32`,
  `W30 L30`), US shoe (`US 7`–`US 9`), and three spellings of one-size. Plus
  two concrete false positives: `"s" in "us 9"` is `True`, so a request for a
  small top returns shoes, and `"l" in "xl"` is `True`, so a request for L
  returns XL.
- *What I changed:* I wrote the family-scoped matching rule into the Tool
  Inventory spec *before* any code existed, instead of discovering it as a bug
  in Milestone 5. `_size_family()` classifies both sides and only matches
  within a family, with One Size matching everything. Then I had 18 assertions
  written covering every trap case, which is what `notes/data-notes.md`
  records. All 18 pass.

**Moment 2 — the trace printed on every run**

- *What I asked for:* I asked for the loop to be run both ways — once plain and
  once with `--trace` — to check the flag actually did something, before I
  pasted anything into Sample Run.
- *What came back:* Identical output. The starter's `trace.step()` calls
  `print()` unconditionally, so once I had added trace calls inside
  `run_agent()`, every ordinary run dumped ten steps of diagnostics at the
  user, and `--trace` changed nothing at all.
- *What I changed:* I had `trace.py` take a `_printing` flag that `start_trace()`
  sets, so steps are always *recorded* — `get_trace()` still returns everything
  — but only *printed* when a trace was deliberately started. `app.py` calls
  `start_trace()` only for `--trace`; `agent.py`'s `__main__` calls it because
  watching the loop is the whole point of running that file directly. This is
  the one starter file I modified, and it is why the Sample Run output above is
  readable.

**Two smaller ones, for completeness:** running `create_fit_card` three times
with `AI201_CACHE=0` is what showed the captions were genuinely varying rather
than being served from cache; and whole-dollar prices were reaching the model
as `18.0`, which it copied into captions as "$18.0", until a `_money()` helper
formatted them.

**Unit 4 continues this section** — see
[How I Used AI, unit 4](#how-i-used-ai--unit-4) at the end, which covers using
it to argue the opposite verdict and to find the bug in my own scorer.

<!-- ═══════════════════════ UNIT 4 — THE TEST ═══════════════════════ -->

---

## How This Unit Was Tested

Three things about the method, because they decide how every number below
should be read.

**What counts as one try.** Four of the five criteria ask about *several
different queries* — "for 5 different matching queries", "across 5 fit cards
generated for 5 different items", "for 5 queries that each name a price
ceiling". So a try is one repetition of a criterion's whole scenario set, and a
try passes only if every query in the set passed on that repetition. Five
repetitions of a five-query set is 25 runs, not 5. The repetition is what
exposes model variance; the set is what the criterion actually asks about. A
criterion saying "every card contains the price" is not satisfied by four cards
out of five, so a repetition in which one card dropped the price is a failed
try rather than four fifths of one. Full reasoning is in the header of
`scenarios.py`.

**One scenario set serves four criteria.** Criteria 1, 3, 4 and 5(a) are all
measured on the same five matching queries, because the set was built to
satisfy all four at once: each query names a price ceiling, each matches at
least one listing, and the five select five *distinct* items in five distinct
categories. Which item each query selects was checked against the data before
the queries were written down — `search_listings` and `compare_prices` are both
deterministic, so that is knowable without spending a model call. Two of the
five are chosen for the loop path they exercise rather than the item: the jeans
query rejects a candidate and re-plans, and the mary janes query finds every
candidate overpriced and so is the only scenario that reaches the loop's `else`
clause.

**The verdicts are computed, not eyeballed.** `run_eval.py` deliberately leaves
the PASS/FAIL columns blank. `score.py` fills them in by applying `criteria.md`.
That is a deliberate choice and worth defending: the scenario set is 50 runs per
label, and marking 50 runs by hand is not a test of the agent but a test of
whether I still remember on row 40 what I decided on row 3 — and the direction
that drift reliably runs in is the one that flatters the agent. Every clause of
every criterion is quoted in a docstring next to the code that checks it, so the
mapping is auditable. Three clauses needed interpreting before they could be
executed at all; each is marked `INTERPRETATION` in `score.py` and the one that
changes a verdict is argued out below.

The judgement is still mine. It is written in code instead of in my head, which
makes it re-runnable and makes it possible to disagree with.

**The scorer was tested too, because it is part of the apparatus.** The first
version of `score.py` returned MET on all five criteria. That is exactly when an
instrument deserves suspicion, so I ran nine deliberately corrupted runs through
it — a blanked fit card, a branch that walks past itself, an off-by-one in the
trace ids, a card describing the wrong candidate, a missing platform, a missing
price, five identical openings, a result above the ceiling, an unactionable
empty message. It caught eight and **missed one**, and the reason it missed was
a real bug: it matched title words as substrings, so `hat` inside `that` counted
as naming a bucket hat, and `tee` — shared by three candidates in one result
set — counted as identifying any of them. Part of that clean sweep was the
scorer being unable to fail. Fixed to whole-word matching, re-run, all nine
caught. A verdict of MET from a checker with no demonstrated ability to return
FAIL is not evidence.

```
CAUGHT  C1 blank one fit card                    C1: 4/5
CAUGHT  C2 branch does not stop                  C2: 4/5
CAUGHT  C3 off-by-one id mismatch                C3: 3/5
CAUGHT  C3 card describes a rival candidate      C3: 3/5
CAUGHT  C4 platform missing                      C4: 4/5
CAUGHT  C4 price missing                         C4: 4/5
CAUGHT  C5a result over ceiling                  C5: 4/5
CAUGHT  C5b unactionable message                 C5: 4/5
CAUGHT  C4 'that' must not count as 'hat'        C4: 4/5

all negative controls caught: True
```

---

## Run Log — Before

50 runs: 10 scenarios, 5 tries each, caching off, 62 model calls, 0 crashes.
Produced by `run_eval.py::main`, scored by `score.py::score`.

| Criterion | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 1. A matching query completes all three tools | 4 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 2. An impossible query stops before the second tool | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 3. The item the search found is the item the next tool received | 5 of 5 | FAIL | PASS | PASS | PASS | PASS | **MISSED (4/5)** |
| 4. The fit card names the item, its price and its platform, every time | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 5. A stated price ceiling is never exceeded, and the empty-search message is actionable | (a) 5 of 5, (b) 3 of 3 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |

Criterion 5 has two parts and the row above is the conjunction of both.
Separately:

| Part | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 5(a) no result above the stated ceiling | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 5(b) the empty-search message quotes a constraint | 3 of 3 | PASS | PASS | PASS | n/a | n/a | **MET (3/3)** |

5(b)'s target is 3 of 3 for three *different* kinds of empty, so a try there is
a query rather than a repetition. The path makes no model call, so every
repetition should be identical; `score.py` asserts that rather than assuming it,
and all five repetitions of all three queries agreed.

### Real output, one try per criterion

**Criterion 1** — `agent.py::run_agent` completing all three tools. Scenario
"outerwear — track jacket", try 3:

```
selected: 90s Track Jacket — Navy/White Stripe  $45  poshmark
fit_card (tools.py::create_fit_card):
That crisp navy track jacket has the exact kind of effortless 90s weight you
hunt for all weekend. Toss it over wide-leg khakis and heavy boots to cut the
athletic edge, or keep it slouchy with straight-leg denim. Grab this piece on
Poshmark for $45 before I change my mind.
```

**Criterion 2** — `agent.py::_no_results_message`, reached via the first branch
in `run_agent`. Scenario "impossible query stops before tool 2", try 1:

```
[1] parse_query
      in:  designer ballgown size XXS under $5
      out: description='designer ballgown', size='XXS', max_price=5.0
[2] search_listings (via MCP)
      in:  description='designer ballgown', size='XXS', max_price=5.0
      out: [] (empty)
[3] branch
      out: search_results == [] (empty list)
      →    stopping before suggest_outfit — nothing to style

Nothing in the 40 listings matches all of: keywords: designer, ballgown; price at or under $5; size XXS.
  To get results, raise the $5 ceiling, drop or widen the size filter (XXS), or use words closer to how a seller would title it — this data runs on terms like vintage, y2k, 90s, graphic tee, denim, oversized, grunge, linen.
```

Three steps, and `suggest_outfit` is not one of them. The happy path is eight.

**Criterion 3** — the identity check, read from the trace as the criterion
specifies. Scenario "bottoms — jeans", try 2, which is the scenario that
rejects a candidate and re-plans:

```
[3] compare_prices
      in:  candidate 1 of 4: lst_001 at $38
      out: overpriced
[4] branch
      out: rejected lst_001
      →    overpriced — going round again with the next candidate
[5] compare_prices
      in:  candidate 2 of 4: lst_037 at $30
      out: fair
[6] select_item
      in:  candidate 2 of 4
      out: Straight Leg Black Jeans — Faded ($30.0, thredUp)
      →    session['selected_item']['id'] = lst_037
[7] suggest_outfit
      in:  selected_item id = lst_037 (read back from session), wardrobe items = 10
```

`lst_037` on step 6, `lst_037` on step 7, and `lst_037` is in
`session["search_results"]`. The index advanced past `lst_001` without the
session and the call drifting apart, which is the exact failure the criterion
was written for.

**Criterion 4** — a card carrying price and platform. Scenario "shoes — mary
janes", try 2, the all-candidates-overpriced path:

```
price_warning (agent.py::run_agent, else clause):
The only match came out above the going rate for its category. Showing the best
keyword match anyway — $55.00 is overpriced — $11.00 above the $44.00 median of
3 comparable listings ($20.00–$48.00, same category).

fit_card (tools.py::create_fit_card), 302 chars, 3 sentences:
Glossy black patent platform mary janes are sitting in my depop shop for $55.
Throw them on with baggy straight-leg denim and a cropped zip hoodie for that
heavy-soled 90s slouch. Or, let the chunky heel anchor a slouchy white tank and
wide khaki trousers when you want something a little more neutral.
```

**Criterion 5(a)** — every result under the stated ceiling, not just the
selected one. Scenario "accessories — shoulder bag", try 1, ceiling $40,
`session["search_results"]` as `tools.py::search_listings` returned it:

```
ceiling: 40.0
results: lst_039 $38, lst_031 $36, lst_018 $38, lst_035 $20, lst_029 $28,
         lst_021 $29, lst_013 $30, lst_032 $33, lst_025 $34
```

Nine results, highest $38, zero violations. Across all 25 ceilinged runs the
violation count was zero.

**Criterion 5(b)** — all three kinds of empty, from
`agent.py::_no_results_message`:

```
-- ceiling nothing can meet: max_price=5.0 size=None keywords=['vintage','denim','jacket']
Nothing in the 40 listings matches all of: keywords: vintage, denim, jacket; price at or under $5.
  To get results, raise the $5 ceiling, or use words closer to how a seller would title it — ...

-- size nothing is stocked in: max_price=None size='XXS' keywords=['graphic','tee']
Nothing in the 40 listings matches all of: keywords: graphic, tee; size XXS.
  To get results, drop or widen the size filter (XXS), or use words closer to how a seller would title it — ...

-- words not in the data: max_price=None size=None keywords=['sequined','ballgown']
Nothing in the 40 listings matches all of: keywords: sequined, ballgown.
  To get results, or use words closer to how a seller would title it — ...
```

Each quotes a constraint with its value, which is what 5(b) asks for. The third
one also exposes a grammar bug — "To get results, or use words" — logged under
What's Still Broken.

---

## Verdicts and Diagnoses

Verdicts are against the targets as written in unit 3. Two criteria were revised
in this unit (`criteria.md`, originals intact above each revision); both
revisions make the criterion *harder*, and neither is used for the verdicts
below.

| # | Criterion | Target | Verdict | How I decided |
|---|---|---|---|---|
| 1 | A matching query completes all three tools | 4 of 5 | **MET (5/5)** | All 5 repetitions of all 5 matching queries completed `search_listings`, `suggest_outfit` and `create_fit_card` and returned a non-empty card that was not the tool's own empty-case string. 25 runs, 0 failures, 0 crashes. |
| 2 | An impossible query stops before the second tool | 5 of 5 | **MET (5/5)** | 5 of 5. `search_results == []`, no `suggest_outfit` step in the trace, `outfit_suggestion` and `fit_card` both still `None`, and a message that says what to change. Checked the trace rather than the session, so a tool called without being recorded would still have been caught. |
| 3 | The item the search found is the item the next tool received | 5 of 5 | **MISSED (4/5)** | Failed try 1. The three id clauses passed on all 25 runs — the loop never mixed an item up, including on the re-plan path. The clause that failed is the last one, "the fit card's named item must be that listing's title". 4 of 5 against a 5-of-5 target is a miss. |
| 4 | The fit card names the item, its price and its platform, every time | 5 of 5 | **MET (5/5)** | All 25 cards stated the price as a number, named the platform, and named the item or its garment type in the first sentence; all were 2–3 sentences and 180–330 characters against a 2–4 and sub-400 bound; and the 5 openings within each try were distinct 5 times out of 5. |
| 5 | A stated price ceiling is never exceeded, and the empty-search message is actionable | (a) 5 of 5, (b) 3 of 3 | **MET (5/5)** | (a) zero results above the ceiling across 25 runs and 200-odd returned listings, and the parser found the ceiling in every one of the five phrasings. (b) all three messages quote a constraint with its value in all 5 repetitions. |

**One miss, and it is not where I expected it.** Criterion 4 was the one I
called "most at risk" in unit 3, on the grounds that 32 of 40 listings have
`brand` set to `None` and any sentence leaning on the brand would come out as a
fragment. That turned out to be a risk I had already designed away: the caption
prompt never passes `brand` at all, and the stylist system prompt says never to
mention a brand unless given one. The prediction was about a field the prompt
does not use, so it could not have come true.

### Diagnosis: criterion 3, try 1

**Where:** the model's output. Not the tool, not the branch, not the session.

**What happened.** On try 1 of the graphic-tee scenario the loop selected
`lst_033` "Vintage Band Tee — Faded Grey" and the caption came back:

```
Charcoal tour tee with that thin, paper-soft cotton you can't fake. Layer it
over a white tank with loose dark denim for an easy streetwear slouch, or tuck
it into khaki trousers with heavy boots and a cropped jacket. Grab this faded
piece for $19 over on depop before I change my mind.
```

**The mechanism.** The same search returned `lst_006` "Graphic Tee — 2003 Tour
Bootleg Style" and `lst_002` "Y2K Baby Tee — Butterfly Print" alongside
`lst_033`. Of the three words in the selected item's title, `tee` belongs to all
three candidates; only `band` and `grey` belong to `lst_033` alone. The caption
uses neither. It uses `tour` — which belongs to `lst_006` and to no other
listing.

I checked where `tour` came from, because it matters whether the model read it
somewhere or invented it:

```
'tour' in the outfit suggestion passed to create_fit_card:   False
'tour' in any item field the prompt passes:                  False
'tour' in the listing's own description (not passed at all):  False
```

It is in none of them. The model inferred it from the style tag `band tee`,
since band merchandise is tour merchandise, and wrote a word that appears
nowhere in the prompt. Simultaneously it dropped `band`, the one title word that
separates this listing from the other two tees on the same results page.

The fault is in the prompt, and in one line of it. `tools.py::create_fit_card`
said:

```
- Name the item or what kind of thing it is in the first sentence.
```

"or what kind of thing it is" is an explicit licence to paraphrase, and the
model took it. The tool worked, the loop worked, the session was consistent
throughout — all three ids agreed on this very run. What failed is that the
user-facing caption, the only part of the run a user ever sees, described a
different listing from the one being sold to them.

**Why this counts as a miss rather than a quibble.** This is the one place a
reading of the criterion changes a verdict, so the reasoning is worth stating.
Criterion 3's last clause is "the fit card's named item must be that listing's
title". Read literally — the card contains the title verbatim — it fails
essentially every caption, because "Vintage Band Tee — Faded Grey" is a listing
title and not a sentence. Read loosely — the card shares any word with the
title — it passes this card, because `tee` is in it, and would equally pass a
card that was unmistakably about one of the other two tees.

Neither reading is usable, so the clause is read for what `criteria.md` says it
is *for*: "an off-by-one there would style candidate *n* while having written
candidate *n+1* into the session ... nothing in the user-facing output would
look wrong". That purpose makes the question "of the candidates the search
returned, which one is this card describing?" — so the card must use at least
one word belonging to the selected listing and to no other candidate, and must
not fit a rival better. This is the strictest of the three readings and the only
one able to detect the bug the criterion says it exists to detect.

Under the loose reading criterion 3 scores **5/5 MET**; under this one it scores
**4/5 MISSED**. Both numbers are stated here so the choice is visible rather
than buried. I use the strict one.

### The pattern

There is only one miss, so there is no pattern across misses. There is a
pattern across the *near* misses, and it is the one worth naming: every
remaining weakness in this agent is in the caption prompt, and none is in the
loop.

- Criterion 3's failure is the caption dropping the word that identifies the item.
- Criterion 4 passed, but its distinct-openings clause passed *trivially*, and a
  measurement the clause does not make shows the same prompt producing "Scored
  these perfectly faded black straight-leg jeans on thredUp" verbatim on two
  separate tries of the same item.
- Criterion 1 passed, but the thing its 4-of-5 target was justified by is a
  property of `search_listings` that the clause's own precondition excludes.

The loop, the branches, the session and the two deterministic tools did not
produce a single failure in 50 runs. Everything that went wrong, and everything
that nearly went wrong, happened in the one place where a model writes prose
that a user reads.

---

## Loop Trace

One full run, step by step, with the MCP call visible at step 2. Both traces
are lifted from the recorded test run in `results/`, not re-staged for the
write-up. `trace.step()` calls live in `agent.py::run_agent`; formatting is
`trace.py`.

**Happy path** — scenario "bottoms — jeans", try 2. This is the run that
exercises the second branch: candidate 1 is judged overpriced, rejected, and
the loop goes round again.

```
[1] parse_query
      in:  levis 501 jeans under $40
      out: description='levis 501 jeans', size=None, max_price=40.0
[2] search_listings (via MCP)
      in:  description='levis 501 jeans', size=None, max_price=40.0
      out: 4 items: Vintage Levi's 501 Jeans — Medium Wash, Straight Leg Black Jeans — Faded, Baggy Carpenter Jeans — Dark Wash … +1 more
[3] compare_prices
      in:  candidate 1 of 4: lst_001 at $38
      out: overpriced
      →    $38.00 is overpriced — $8.50 above the $29.50 median of 8 comparable listings ($14.00–$36.00, same category and a shared style tag).
[4] branch
      out: rejected lst_001
      →    overpriced — going round again with the next candidate
[5] compare_prices
      in:  candidate 2 of 4: lst_037 at $30
      out: fair
      →    $30.00 is fair — $1.00 below the $31.00 median of 6 comparable listings ($24.00–$38.00, same category and a shared style tag).
[6] select_item
      in:  candidate 2 of 4
      out: Straight Leg Black Jeans — Faded ($30.0, thredUp)
      →    session['selected_item']['id'] = lst_037
[7] suggest_outfit
      in:  selected_item id = lst_037 (read back from session), wardrobe items = 10
      out: **Outfit 1** Pair the Straight Leg Black Jeans — Faded with the White ribbed tank top and the Black cropped zi…
[8] create_fit_card
      in:  outfit = 697 chars, selected_item id = lst_037
      out: Scored these faded black straight leg jeans on thredUp for $30. They have that perfectly worn-in grunge feel t…
```

Step 2 is the MCP call. Steps 3–5 are the loop deciding, not a script running:
the number of iterations comes from the data, because `lst_001` had to be
rejected before `lst_037` could be reached. Step 7's input is read back *out of*
the session rather than reusing the loop variable, which is what makes criterion
3 checkable at all.

**Empty search** — scenario "impossible query", try 1:

```
[1] parse_query
      in:  designer ballgown size XXS under $5
      out: description='designer ballgown', size='XXS', max_price=5.0
[2] search_listings (via MCP)
      in:  description='designer ballgown', size='XXS', max_price=5.0
      out: [] (empty)
[3] branch
      out: search_results == [] (empty list)
      →    stopping before suggest_outfit — nothing to style
```

Three steps against eight, and neither model-calling tool appears. The two
traces being different lengths is the branch working.

**On the MCP move.**

What changed in the code: `mcp_server.py` registers `search_listings` with
typed inputs — `description: str` required, `size: str | None` and
`max_price: float | None` optional — which is what FastMCP builds the published
schema from. `agent.py` no longer imports `search_listings` from `tools.py` at
all; it calls it by name over stdio through `mcp_client.call_tool`, wrapped in
`agent.py::_search_over_mcp`. The other three tools stay direct calls, so the
seam is visible: one tool crosses a process boundary and three do not.

Writing the description was the part that was not code. It is addressed to a
caller that will never see `tools.py`, so it has to carry what the Tool
Inventory used to carry for me: that `max_price` is inclusive and in whole
dollars, that sizes span four incompatible scales and a listing only matches
inside its own, that `brand` is `null` on 32 of the 40 listings, and that an
empty array means "no stock for these constraints" rather than an error. Last
unit the empty case was a note to myself. Here it is a contract.

Checking the inputs against the README found no mismatch, which I did not
expect — the types in the Tool Inventory and the type hints agreed.

**Did anything behave differently?** No, and I checked rather than assuming.
Direct call and MCP call, same arguments, diffed:

```
direct : type list len 10
mcp    : type list len 10
equal  : True

empty case over MCP: []
```

Byte-identical, including the empty list. The reason that is not automatic is
in `mcp_client._unwrap`: the protocol hands back content blocks, so without
that step the loop would have started seeing a JSON string where it used to see
a list, and `if not session["search_results"]` would have been testing a
non-empty string for emptiness and silently never branching.

What *did* change is the failure surface. A direct call cannot fail to be
reached; a subprocess can. `_search_over_mcp` raises `SearchUnavailable` both
when the server cannot be reached and when it returns something that is not a
list, and the second guard matters more than it looks: `None` is falsy, so a
transport fault that returned nothing would have been read by the empty-search
branch as "nothing in the catalogue matches" and reported to the user as a
shopping result. That failure mode did not exist last unit and it is the only
thing the move made worse.

---

## Failure Modes, Triggered on Purpose

Four, not three. The three the unit names, plus the one the MCP move
introduced. Each was triggered deliberately rather than waited for, and each
message below is the real text, copied from the terminal.

The test I applied to each message is the one from the unit brief: could
somebody who cannot see the code read this and know what to do next? Two of
the four already passed it. One passed on the message and failed on everything
around the message. One did not exist last unit.

### 1. Empty search — already handled, no change needed

```
python app.py ask 'designer ballgown size XXS under $5' --trace
```

```
[1] parse_query
      in:  designer ballgown size XXS under $5
      out: description='designer ballgown', size='XXS', max_price=5.0
[2] search_listings (via MCP)
      in:  description='designer ballgown', size='XXS', max_price=5.0
      out: [] (empty)
[3] branch
      out: search_results == [] (empty list)
      →    stopping before suggest_outfit — nothing to style

  Nothing in the 40 listings matches all of: keywords: designer, ballgown; price at or under $5; size XXS.
  To get results, raise the $5 ceiling, drop or widen the size filter (XXS), or use words closer to how a seller would title it — this data runs on terms like vintage, y2k, 90s, graphic tee, denim, oversized, grunge, linen.
```

Produced by `agent.py::_no_results_message`. It names all three constraints
with their values and then names three specific things to change, so there is
something to act on without reading any code. No handler added.

### 2. Empty wardrobe — already handled, no change needed

```
python app.py ask 'denim jacket under $50' --empty-wardrobe
```

```
  Found:    Denim Jacket — Light Wash, Cropped — $42 on poshmark
  Price:    $42.00 is fair — $2.00 above the $40.00 median of 7 comparable listings ($27.00–$75.00, same category and a shared style tag).

  Outfit:   No wardrobe saved yet, so this is general styling advice rather than outfits from your own clothes.

Pair this cropped jacket with high-waisted wide-leg trousers or a ribbed midi skirt to balance the structured shoulders and shorter hemline. Avoid pairing it with stiff, matching light-wash jeans to prevent a dated Canadian tuxedo effect. It suits casual weekend occasions like visiting a weekend flea market or grabbing coffee.

  Fit card: This faded light-wash cropped denim jacket has that perfectly broken-in vintage feel. Snagged it on Poshmark for $42. Throw it over a ribbed midi skirt for weekend coffee runs without leaning into a stiff Canadian tuxedo vibe.
```

Produced by the empty-wardrobe branch of `tools.py::suggest_outfit`. Advice,
not a crash and not an empty string, and the first line says why the advice is
general — the user is told the cause of the difference rather than left to
notice it. The run still completes and still produces a fit card. No handler
added.

### 3. Model unavailable — this one needed a handler

Triggered by changing the last character of `GEMINI_API_KEY` in `.env`, on a
query never run before, so the build cache could not answer it and the request
genuinely had to leave the machine.

**Before the handler.** The message itself was fine. Everything around it was
not:

```
[1] parse_query ...
[2] search_listings (via MCP) ...
[3] compare_prices
      out: fair
[4] select_item
      out: Crochet Halter Top — Cream ($22.0, depop)
      →    session['selected_item']['id'] = lst_023

ModelUnavailable: The model rejected your API key. Check GEMINI_API_KEY in your .env file, or create a fresh key at aistudio.google.com.
```

Two defects, neither of them the wording.

The trace stops at step 4. The run went wrong at step 5, and step 5 is not in
the trace — the one piece of evidence a trace exists to provide was missing at
exactly the point it was needed. That is worse than a bad message, because a
bad message at least tells you something happened.

And the agent had already found a $22 Crochet Halter Top and price-checked it
as fair. Search and `compare_prices` make no model call, so both of those are
established facts, not guesses. They were thrown away with the exception,
because the only thing catching `ModelUnavailable` was the blanket
`except Exception` in `app.py::main`, which has no access to the session.

**After the handler** (`agent.py::_model_down_message`, with the catch around
steps 3 and 4 of `run_agent`):

```
[4] select_item
      in:  candidate 1 of 1
      out: Suede Chelsea Boots — Tan ($44.0, poshmark)
      →    session['selected_item']['id'] = lst_028
[5] branch
      out: ModelUnavailable raised by the model call
      →    stopping after select_item — the search half of the run is kept and reported, the written half is not available

  I found something, but I couldn't reach the model to style it or write the caption.
  What broke: The model rejected your API key. Check GEMINI_API_KEY in your .env file, or create a fresh key at aistudio.google.com.
  I did get as far as finding one: Suede Chelsea Boots — Tan — $44 on poshmark
  Price check: $44.00 is fair — $4.00 below the $48.00 median of 3 comparable listings ($20.00–$55.00, same category).
  That part of the run doesn't use the model, so it's a real result — only the outfit and the caption are missing.
  To try: fix the key or the connection above, then run the same query again — the search will return the same item, so nothing is lost by retrying.
```

The failure is now a trace step, and the deterministic half of the run
survives it. The key was put back immediately afterwards; `git diff` on `.env`
is empty because `.env` is gitignored, so the only record that it was ever
broken is this section.

`QuotaGuard` is caught by the same handler. It is a different cause with the
same shape — the model call did not happen — and it would have hidden the
session in exactly the same way.

**The handler then caught one for real, which I did not arrange.** On the last
end-to-end check before submitting, the service returned a genuine 503:

```
[5] suggest_outfit
      in:  selected_item id = lst_033 (read back from session), wardrobe items = 10
[6] branch
      out: ModelUnavailable raised by the model call
      →    stopping after select_item — the search half of the run is kept and reported, the written half is not available

  I found something, but I couldn't reach the model to style it or write the caption.
  What broke: Couldn't reach the model: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The service is currently unavailable.', 'status': 'UNAVAILABLE'}}
  I did get as far as finding one: Vintage Band Tee — Faded Grey — $19 on depop
  Price check: $19.00 is fair — $1.50 below the $20.50 median of 12 comparable listings ($15.00–$28.00, same category and a shared style tag).
  That part of the run doesn't use the model, so it's a real result — only the outfit and the caption are missing.
  To try: fix the key or the connection above, then run the same query again — the search will return the same item, so nothing is lost by retrying.
```

A different cause from the bad key — nothing to do with the user, nothing they
can fix — and the handler written for the bad key carried it anyway, because it
reports what broke and what survived rather than guessing why. The one line that
is now wrong in this case is "fix the key or the connection", which is the wrong
advice for a server-side outage; the right next action is simply to wait. That
is a sharper version of the same handler I would write next: branch the "to try"
line on whether the cause was authentication or availability.

### 4. MCP server unreachable — the failure mode the move introduced

This one did not exist last unit. Before Milestone 1 a broken search was a
Python exception inside one process. Now it is a subprocess that might not
start, a handshake that might not complete, and a tool name that might not be
registered. Triggered by pointing `mcp_client.SERVER` at a file that is not
there:

```
[1] parse_query
      in:  vintage graphic tee under $30
      out: description='vintage graphic tee', size=None, max_price=30.0

SearchUnavailable: The search tool couldn't be reached over MCP, so I have nothing to search.
  What broke: Couldn't call 'search_listings' over MCP: unhandled errors in a TaskGroup (1 sub-exception)
Check that mcp_server.py runs on its own first:
    python mcp_server.py
If it exits immediately with an error, fix that before coming back here.
  To try: run `python mcp_server.py` on its own — if it exits with an error, that error is the cause. `python mcp_client.py` should list search_listings.
```

Produced by `agent.py::_search_over_mcp`. The protocol's own error text
("unhandled errors in a TaskGroup") is useless on its own, which is the whole
reason the handler names two commands that locate the fault instead of
reprinting it and stopping.

`_search_over_mcp` also raises `SearchUnavailable` when the server returns
something that is not a list. That matters more than it looks: the loop's first
branch tests `search_results` for emptiness, and `None` is falsy, so a
transport fault that returned nothing would have been read by the branch as "no
stock matches your query" and reported to the user as a shopping result. A
broken pipe and an empty catalogue must not look the same to the branch.

---

## The Improvement

**Stretch features added in this unit**, declared up front: a second tool was
*not* moved onto MCP, retry-with-looser-constraints was *not* added, and **a
second improvement from the diagnosis was**, measured in the same format as the
first. Three run logs follow: before, after one change, after two.

### Improvement 1 — the one the diagnosis named

**What I changed.** One rule in the `create_fit_card` prompt in `tools.py`.

Before:

```
- Name the item or what kind of thing it is in the first sentence.
```

After:

```
- The first sentence must name the item in the listing's own words: at least
  one word from the title "Vintage Band Tee — Faded Grey" has to appear in it.
  Do not rename the garment and do not swap a title word for a near-synonym of
  your own — several similar items are listed at once, and the caption has to
  make clear which one this is.
```

**Which failure it was meant to fix.** The only miss: criterion 3, try 1, where
the caption for `lst_033` read "Charcoal tour tee". The diagnosis put the fault
on the phrase "or what kind of thing it is", which licenses exactly the
paraphrase that lost the identifying word. This is the "rewrite one prompt"
option, and it is the one the diagnosis pointed at rather than the one that was
easiest.

The same card, before and after:

```
before (try 1):  Charcoal tour tee with that thin, paper-soft cotton you can't
                 fake. ... Grab this faded piece for $19 over on depop ...

after  (try 1):  There is nothing quite like a broken-in Vintage Band Tee that
                 already has years of real wear built into the cotton. Grab
                 this faded grey piece for $19 before it heads to my depop. ...
```

### Run Log — After (improvement 1)

50 runs, 5 tries, caching off, 60 model calls, 0 crashes.

| Criterion | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 1. A matching query completes all three tools | 4 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 2. An impossible query stops before the second tool | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 3. The item the search found is the item the next tool received | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 4. The fit card names the item, its price and its platform, every time | 5 of 5 | FAIL | FAIL | FAIL | FAIL | FAIL | **MISSED (0/5)** |
| 5. A stated price ceiling is never exceeded, and the empty-search message is actionable | (a) 5 of 5, (b) 3 of 3 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |

Side by side:

| Criterion | Before | After 1 | Change |
|---|---|---|---|
| 1 | MET (5/5) | MET (5/5) | — |
| 2 | MET (5/5) | MET (5/5) | — |
| 3 | **MISSED (4/5)** | **MET (5/5)** | **fixed** |
| 4 | **MET (5/5)** | **MISSED (0/5)** | **broken** |
| 5 | MET (5/5) | MET (5/5) | — |

**Did it help?** It did exactly what it was aimed at and it made the agent worse
overall. Criterion 3 went from MISSED to MET and has not failed since. Criterion
4 went from a clean 5 of 5 to 0 of 5.

The mechanism of the regression, because "it broke" is not a diagnosis either.
The price stopped being a number and started being a word:

```
try 1: Scored these thrashed Straight Leg Black Jeans — Faded for thirty bucks
       on thredUp and haven't taken them off since.
try 2: ... Scored off thredUp for thirty bucks, they have the kind of slouchy,
       grunge weight ...
try 3: Scored this perfectly faded vintage band tee over on depop for nineteen
       bucks.
```

Five of the 25 cards lost the digits. No card stated a *wrong* price — "thirty
bucks" for a $30 item is accurate — but criterion 4 asks for the price "as a
number", and it asks for that because a spelled-out price stops being accurate
the moment a listing is not a round number of dollars. The five failures fall
one per try, four on the jeans scenario and one on the tee, so every try
contains a failing card and the criterion scores 0 of 5. That spread is worth
noticing on its own: a criterion reduced strictly across a five-item set turns a
20% per-card fault into total failure of the criterion, which is what "every
card" was written to mean.

Why the change caused it is partly inference and I will not overclaim. What is
certain is that the price rule was not touched, and that the old rule — "State
the price ($30) exactly once" — names the digits without ever saying the digits
are the requirement, so "thirty bucks" always satisfied it as written. What
changed around it is that the new naming rule is long, emphatic about copying
the listing's words, and makes the opening stiffer; the model appears to have
loosened register elsewhere in the sentence to compensate. The rule was
satisfiable in words all along; the first improvement is what made the model
start taking that option.

A second side effect, which no criterion measures: the title rule is now obeyed
literally enough that some cards paste the raw listing title into the prose,
em dash included — "these thrashed Straight Leg Black Jeans — Faded for thirty
bucks". That reads like a database field in a sentence.

### Improvement 2 — fixing the regression (stretch)

**What I changed.** One more rule in the same prompt, nothing else.

Before:

```
- State the price ($30) exactly once.
```

After:

```
- State the price exactly once, in digits with the dollar sign, written
  exactly as "$30" — not spelled out in words, not rounded, not approximated.
```

**Which failure it was meant to fix.** Criterion 4's 0-of-5, and nothing else.
The naming rule from improvement 1 is left exactly as it is, because criterion 3
depends on it now.

### Run Log — After (improvement 2)

50 runs, 5 tries, caching off, 60 model calls, 0 crashes.

| Criterion | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 1. A matching query completes all three tools | 4 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 2. An impossible query stops before the second tool | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 3. The item the search found is the item the next tool received | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 4. The fit card names the item, its price and its platform, every time | 5 of 5 | PASS | PASS | PASS | PASS | FAIL | **MISSED (4/5)** |
| 5. A stated price ceiling is never exceeded, and the empty-search message is actionable | (a) 5 of 5, (b) 3 of 3 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |

**Did it help?** Yes, substantially, and not enough. The fault it targeted went
from 5 cards in 25 to 1 in 25:

| | Before | After 1 | After 2 |
|---|---|---|---|
| Cards with no numeric price | **0 of 25** | **5 of 25** | **1 of 25** |
| Criterion 4 | MET (5/5) | MISSED (0/5) | MISSED (4/5) |

An 80% reduction in the fault rate moves the criterion from 0 of 5 to 4 of 5 and
no further, because criterion 4 says *every* card. One bad card in a try fails
that try, so the last remaining instance — one card in 25 — costs a whole try.
It is the same fault, in the same form, on a different item:

```
accessories — shoulder bag, try 5, price $38:
That classic Mini Shoulder Bag in tan leather is thirty-eight dollars over on
poshmark. It's the easiest way to pull together a slouchy grey sweatshirt and
wide khakis without looking like you tried too hard.
```

"thirty-eight dollars", after a rule that says in as many words "in digits with
the dollar sign, written exactly as \"$38\" — not spelled out in words". The
instruction is unambiguous, it is obeyed 24 times out of 25, and at temperature
0.9 it is disobeyed once. That is the finding, and it is more useful than the
improvement: **an exact string required in model output cannot be made reliable
by asking more firmly.** Three phrasings of the rule produced fault rates of
0%, 20% and 4%, and none of them produced 0% by instruction — the 0% in the
before-run was luck at a lower difficulty, since the old rule was satisfiable in
words too and the model simply had not taken that option yet.

### Where the agent ended up

| Criterion | Before | After 1 | After 2 | Net |
|---|---|---|---|---|
| 1. Completes all three tools | MET (5/5) | MET (5/5) | MET (5/5) | — |
| 2. Impossible query stops early | MET (5/5) | MET (5/5) | MET (5/5) | — |
| 3. Item found is item received | **MISSED (4/5)** | MET (5/5) | **MET (5/5)** | **fixed** |
| 4. Card names item, price, platform | MET (5/5) | MISSED (0/5) | **MISSED (4/5)** | **broken** |
| 5. Ceiling held, empty message actionable | MET (5/5) | MET (5/5) | MET (5/5) | — |

**The honest summary: I traded one miss for another.** The agent began the unit
missing one of five criteria and ends it missing one of five criteria, at the
same 4-of-5 rate, in a different place. Criterion 3 is fixed and has not failed
in 50 runs since. Criterion 4 was collateral damage from fixing it, and the
second change recovered most but not all of what the first change cost.

I am not reverting either one, and the reason is in the numbers above rather
than in a preference. Criterion 3's failure showed a user a caption describing a
different listing from the one being sold to them. Criterion 4's remaining
failure shows a user "thirty-eight dollars" instead of "$38", which is accurate
and merely informal — it only becomes a real defect on a listing whose price is
not a round number, and there are none in this dataset. If I have to carry one
miss, that is the one to carry. But it is still a miss against a target I set,
it is reported as one, and the fix that would actually close it is to stop asking
the model for the facts at all — which is problem 1 under What's Still Broken.

---

## What's Still Broken

One criterion is still missed: **criterion 4, at 4 of 5 against a 5-of-5
target**, because one card in 25 writes "thirty-eight dollars" instead of "$38".
That and five other things, ordered by how much I think they matter rather than
by how easy they are.

**1. Criterion 4 cannot be closed by instruction, and that is the real finding
of this unit.**

Three phrasings of one prompt rule produced three fault rates — 0%, 20%, 4% —
and the only one that reached zero did so by luck rather than by being
unambiguous: the original rule, "State the price ($30) exactly once", was
satisfiable in words all along, and the model had simply not yet taken that
option. The rule it ends on says "in digits with the dollar sign, written exactly
as \"$38\" — not spelled out in words", and is disobeyed once in 25 cards at
temperature 0.9. Asking more firmly is not a mechanism; it is a hope with a
measured success rate of 96%.

Fifty runs before, fifty after, fifty after that — 150 runs — and the loop, both
branches, the session, `search_listings` and `compare_prices` produced zero
failures between them. Every miss in this unit came out of `create_fit_card`.
That prompt now carries a rule to copy the title's words, a rule to write the
price in digits, and a rule not to sound like a product page, and the first two
pull against the third: improvement 1 is a worked demonstration that tightening
one loosened another somewhere I was not looking.

What I would do, and it is the first thing I would do in the next unit: stop
asking the model for the facts at all. The price and the platform are known
strings. A caption that must contain them exactly is a caption with a slot in
it, not a caption a model at temperature 0.9 should be trusted to transcribe. I
would have `create_fit_card` ask for the prose only and assemble the fact
sentence in Python, which turns criterion 4's price and platform clauses from
things that get *checked* into things that cannot fail, and lets the three
fighting rules drop back to one.

Why I stopped here instead: that is a change to what the tool returns, not to a
prompt, and this unit's rule allows the MCP move plus the improvement. I spent
the improvement on the diagnosis's own target and the stretch allowance on the
regression it caused. Taking a third bite would have meant three changes between
the before-run and the last after-run, and the one thing this unit is actually
measuring is whether a change can be attributed to its cause.

**2. Criterion 4's distinct-openings clause could not fail, and the thing it was
written to catch is happening.**

Revised in `criteria.md` with the original left in place. The clause compared
openings across five *different* garments, which is nearly impossible to fail,
and it passed 5 of 5 while telling me nothing. Measured the way it was meant —
one item captioned repeatedly — `lst_037` gives 4 of 5 distinct openings, with
"Scored these perfectly faded black straight-leg jeans on thredUp" appearing
verbatim on two separate tries, and 3 of 5 if only the first four words are
compared. The mail merge the clause exists to prevent is partly there.

Why I stopped: the revision is the finding. Measuring it properly needs the same
item run five times as its own scenario, and acting on it means a fourth rule in
a prompt that already has three too many — which is problem 1, and it should be
fixed there rather than patched here.

**3. Criterion 1's target rests on something criterion 1 cannot measure.**

Also revised, original left in place. The 4-of-5 target was justified by "roughly
one query in five that a human would call reasonable" finding nothing, but the
clause begins "given a query that matches at least one listing", so the failure
the number was chosen for is excluded by the clause's own precondition.
`probe_synonyms.py` measures it directly and the original estimate was sound,
slightly optimistic:

```
4 of 15 reasonable alternative phrasings failed to find the garment
the seller's own wording finds — that is 27%, against the 20% that
criterion 1's 4-of-5 target was set on.

lst_012  sweatshirt    ->  jumper                 0 hits
lst_010  windbreaker   ->  shell jacket           4 hits, none of them it
lst_032  shacket       ->  overshirt              0 hits
lst_039  shoulder bag  ->  small handbag          1 hit,  not it
```

The two that return hits without returning the right garment are the worse
half: the user is styled an item they did not ask about and nothing in the
output says so. No criterion catches that, and the revised clause only catches
the zero-hit version of it.

What I would do: a synonym table mapping the obvious pairs onto the vocabulary
the data actually uses — a dozen entries would cover these four. I did not,
because it is a change to `search_listings`, which is the tool now published
over MCP, and changing a tool's behaviour in the same unit I published its
contract is the wrong order to do things in.

**4. The empty-search message has a grammar bug when the query names no
constraints but keywords.**

```
Nothing in the 40 listings matches all of: keywords: sequined, ballgown.
  To get results, or use words closer to how a seller would title it — ...
```

"To get results, or use words" — the dangling "or" appears because
`agent.py::_no_results_message` builds the fixes list conditionally and the
price and size clauses are both absent, leaving the final "or ..." to lead. It
passes criterion 5(b), which asks only that a constraint be quoted with its
value, and it is a one-line fix in list assembly. It is still the first thing a
user sees when their words are not in the data, which is the most common way
this agent fails. Not fixed because it is not what the diagnosis named and this
unit allows one change; it is a two-minute job in the next.

**5. `MAX_ITERATIONS` is still never reached, so the stop condition is
untested.**

`trace.check_iterations` is called every time round the loop and the ceiling is
10, but the largest result set in any of these 150 runs was 10 items and the
loop breaks as soon as one candidate is not overpriced. The mary janes scenario
is the closest thing to a test — every candidate overpriced — and it has one
result. The guard has never fired, so I do not actually know it works. Forcing
it would mean a scenario with more than 10 overpriced candidates in one
category, which this 40-row dataset cannot produce.

**6. Nothing checks that the outfit only names clothes the user owns.**

`suggest_outfit`'s prompt says "Do not suggest anything they do not own" and
nothing verifies it. The wardrobe is a known list of names, so this is
mechanically checkable, and it is the obvious sixth criterion. It is not a miss
because I never wrote it down as a target — which is the honest reason it is in
this section and not in the table.

---

### If I missed nothing, were the targets low?

I missed one of five, so the question is still worth answering, and the answer
is: two of them were, in a specific way. Criteria 2 and 5(a) are both pure
deterministic paths — one `if` on a list length, one `<=` on a parsed float —
and both came out 5 of 5 across 150 runs. That is not an agent passing a test,
it is arithmetic. I set them at 5 of 5 on purpose, reasoning that "a flaky
result here would be information", and that reasoning holds: they are cheap
regression guards and they would have screamed if the MCP move had changed the
return shape. But they were never going to tell me anything about the parts of
this system that can actually vary.

The criterion I would tighten is 4, and the revision in `criteria.md` is that
tightening. Criteria 1 and 2 were given to me; of the three I wrote, criterion 3
is the one that earned its place — it is the only one that found something, and
it found it in a part of the run I would not have thought to look at, because it
was written to catch a loop bug and it caught a caption bug instead.

---

## How I Used AI — Unit 4

*Continues the unit 3 section of the same name, above.*

In this unit I used Claude for four things, and the fourth is the one worth
recording.

**Arguing the opposite verdict.** The unit suggests pasting a criterion, its
target, the tries and the verdict, and asking for the strongest case against.
I did that for criterion 3, because a 4-of-5 miss resting on one caption is
exactly the kind of verdict that is convenient to talk yourself out of. The
counter-argument was good: the three id clauses passed, the loop was provably
consistent, no user was shown the wrong item's *price* or *platform*, and the
clause I failed it on is the vaguest in the criterion. I kept the MISSED anyway,
and the reason is in the diagnosis — the clause exists to catch a wrong-item
failure, and a caption describing a different listing on the same results page
is a wrong-item failure even when the ids agree. But the argument changed how I
wrote the verdict up: both readings and both numbers are now in the README,
rather than only the one I chose.

**Reading the failure messages as a user would.** I pasted the three failure
messages in and asked what a user who cannot see the code would try next, with
the instruction not to rewrite them. Two were actionable. The model-unavailable
one was actionable *about the key* and said nothing about the run, which is what
sent me looking at what the exception was discarding — and the handler I added
reports the item and the price check because of that, not because the message
itself needed rewording.

**Writing the MCP tool description.** I wrote it first, then asked what a caller
who could not see the implementation would still not know. The answer was units
and scales: I had written "max_price" without saying inclusive or what currency,
and I had not mentioned that a size only matches inside its own family, which is
the single most surprising thing about the tool. Both went in.

**Testing my own scorer, which I would not have thought to do.** `score.py`
came back MET on all five criteria the first time. I asked Claude to find ways
the scorer could return MET on a run that should fail, and the useful answer was
not about the criteria at all: substring matching means `hat` is inside `that`,
so every caption containing the word "that" counted as naming a bucket hat, and
`tee` is shared by three candidates in one result set so it identified none of
them. I built nine deliberately corrupted runs as negative controls; the first
version caught eight. Fixing the substring bug is what turned criterion 3 from
MET to MISSED — the only miss in the unit came out of testing the test, and
without it the whole run would have been a clean sweep produced by an instrument
with no demonstrated ability to return FAIL.

What I did not use it for: deciding the verdicts, or writing the criteria. Both
were mine, and the one time the two disagreed is written up above.

<!-- ═════════════════════════════════════════════════════════════════════

     SUBMISSION CHECKLIST — unit 3

       [x] criteria.md has five numbered criteria, each with a target
       [x] Each criterion has a reason underneath it
       [x] All five unit 3 sections above have real content
       [x] Tool Inventory: all three tools, inputs WITH TYPES, a specific
           return value, and the empty case
       [x] Planning Loop names the branch rule and agent.py::run_agent
       [x] Sample Run: one full query plus the three per-tool tests, as text
       [x] At least four new commits
       [x] Repository URL submitted — WRITE IT DOWN, you submit the same one
           next unit

     SUBMISSION CHECKLIST — unit 4

       [x] mcp_server.py exists with one tool registered
           (or a written record of exactly where the rewire broke)
       [x] Run Log — Before, five criteria, five tries each
       [x] Real output pasted underneath, naming file and function
       [x] A verdict on every criterion
       [x] A diagnosis for every miss, naming a place AND a mechanism
       [x] Loop Trace, with the MCP call visible in it
       [x] All three failure modes triggered and handled
       [x] One improvement, with Run Log — After in the same format
       [x] What's Still Broken
       [x] At least four new commits
       [x] The SAME repository URL as last unit

     Do not delete and recreate this repository. Your commit history is what
     shows your criteria existed before your results did.
     ═════════════════════════════════════════════════════════════════════ -->

---

📖 **How to run this project: [RUNNING.md](RUNNING.md)**
