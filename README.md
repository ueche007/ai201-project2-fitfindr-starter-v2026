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

Two different things, and it's worth keeping them apart.

**AI inside the app.** Two of my four tools call a model at runtime, because
that's the assignment: `suggest_outfit` and `create_fit_card` both go through
`generate()` to Gemini. The other two, `search_listings` and `compare_prices`,
are plain Python with no model anywhere in them. That split is deliberate and
it's why I can test half of this agent exactly — the no-model half gives the
same answer every time, so when something changes between runs I already know
which half it came from.

I also used `generate.token_counts()` to get the real cost of a run from what
the service reported, rather than estimating it off a pricing page.

**AI as a coding tool.** I used Claude Code to write Python from specs I'd
already decided on — the tool signatures in my Tool Inventory, the size-family
rules, the loop structure — and for the ordinary work of boilerplate, syntax
and tracking down bugs. It was quicker than typing it myself and it caught slips
I'd have spent an evening on. What it did not do is decide what this agent is,
what the tools return, where the branches go, or what "working" means for it.
Those are in `criteria.md` and the Tool Inventory, and they're mine.

Two cases where running a check changed a decision before I wrote code:

**The size filter.** Before writing `search_listings` I had a script written to
list every distinct `size` value in `listings.json` and show me how a naive
filter would behave against it. There are 22 distinct size strings across four
scales that don't compare: letters (`S`, `M`, `S/M`, `XL (oversized)`), waist
(`W27`–`W32`, `W30 L30`), US shoe (`US 7`–`US 9`), and three spellings of
one-size. Two things jumped out: `"s" in "us 9"` is `True`, so asking for a
small top returns shoes, and `"l" in "xl"` is `True`, so asking for L returns
XL. I decided on family-scoped matching off the back of that and wrote it into
the Tool Inventory spec *before* any code existed, instead of finding it as a
bug in Milestone 5. `_size_family()` sorts both sides into a family and only
matches inside one, with One Size matching everything. Then I had 18 assertions
written covering every trap case; `notes/data-notes.md` records them and all 18
pass.

**The trace printed on every run.** I ran the loop twice, once plain and once
with `--trace`, to check the flag actually did something before I pasted
anything into Sample Run. The output was identical. The starter's
`trace.step()` calls `print()` no matter what, so once I'd added trace calls
inside `run_agent()`, every ordinary run dumped ten steps of diagnostics at the
user and `--trace` meant nothing. I fixed it by having `trace.py` keep a
`_printing` flag that `start_trace()` sets, so steps are always *recorded* —
`get_trace()` still returns all of them — but only *printed* when a trace was
started on purpose. `app.py` starts one only for `--trace`; `agent.py`'s
`__main__` always starts one, because watching the loop is the entire reason to
run that file directly. This is the one starter file I changed, and it's why the
Sample Run output above is readable.

**Two smaller ones:** running `create_fit_card` three times with `AI201_CACHE=0`
is how I confirmed the captions were really varying rather than being served
from the cache; and whole-dollar prices were reaching the model as `18.0`, which
it copied into captions as "$18.0", until I added a `_money()` helper.

**Unit 4 continues this section** — see
[How I Used AI, unit 4](#how-i-used-ai--unit-4) at the end.

<!-- ═══════════════════════ UNIT 4 — THE TEST ═══════════════════════ -->

---

## How This Unit Was Tested

Three things about how I ran this, because they change how every number below
should be read.

**What counts as one try.** Four of my five criteria ask about *several
different queries*, not one query run several times — "for 5 different matching
queries", "across 5 fit cards generated for 5 different items", "for 5 queries
that each name a price ceiling". So a try is one full pass through a criterion's
whole set of scenarios, and a try only passes if every query in that set passed
on that pass. Five passes over a five-query set is 25 runs, not 5. The repeating
is what shows me where the model varies, and the set of five is what the
criterion is actually asking about. A criterion saying "every card contains the
price" isn't satisfied by four cards out of five, so a pass where one card
dropped the price is a failed try and not four fifths of one. The longer version
of this reasoning is at the top of `scenarios.py`.

**One set of five queries covers four criteria.** Criteria 1, 3, 4 and 5(a) all
run on the same five matching queries, because I built the set to satisfy all
four at once: each query names a price limit, each one actually matches
something, and the five of them pick five *different* items in five different
categories. I worked out which item each query picks before writing them down —
`search_listings` and `compare_prices` give the same answer every time, so I
could figure that out without spending a single model call. Two of the five are
in there for the path they take rather than the item: the jeans query makes the
loop reject a candidate and go round again, and the mary janes query makes every
candidate come out overpriced, so it's the only scenario that reaches the last
part of my loop.

**The verdicts are worked out in code, not by eye.** `run_eval.py` leaves the
PASS/FAIL columns blank on purpose. `score.py` fills them in by checking
`criteria.md`. I did it that way for a reason worth saying out loud: my scenario
set is 50 runs per measurement, and marking 50 runs by hand isn't really a test
of my agent, it's a test of whether I still remember on row 40 what I decided on
row 3 — and if I drift, I know which way I'll drift, because the flattering
answer is always sitting right there. Every part of every criterion is quoted in
a comment next to the code that checks it, so anyone can compare the two and
tell me I read it wrong. Three parts needed me to decide what they meant before
I could check them at all; each one says so in `score.py`, and the one that
actually changes a verdict I argue out below.

The judgement is still mine. It's written in code instead of in my head, which
means I can re-run it and other people can see what I did.

**I tested my checker too, because it's part of the setup.** The first version
of `score.py` came back MET on all five criteria. That's exactly when I should
stop trusting a tool, so I built nine runs that I broke on purpose — a blanked
fit card, a branch that walks straight past itself, an off-by-one in the trace
ids, a card describing the wrong item, a missing platform, a missing price, five
identical openings, a result over the price limit, and an empty-search message
with nothing useful in it. It caught eight and **missed one**, and the reason it
missed was a real bug: I was comparing title words as pieces of words instead of
whole words, so "hat" inside "that" counted as naming a bucket hat, and "tee" —
which three candidates in one search share — identified none of them. So part of
my clean sweep was just my checker being unable to fail. I fixed it to match
whole words, re-ran, and all nine got caught. A MET from a checker that has
never been shown to return FAIL isn't evidence of anything.

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

Criterion 5 has two parts, and the row above only says MET if both of them
pass. Here they are separately:

| Part | Target | Try 1 | Try 2 | Try 3 | Try 4 | Try 5 | Verdict |
|---|---|---|---|---|---|---|---|
| 5(a) no result above the stated ceiling | 5 of 5 | PASS | PASS | PASS | PASS | PASS | **MET (5/5)** |
| 5(b) the empty-search message quotes a constraint | 3 of 3 | PASS | PASS | PASS | n/a | n/a | **MET (3/3)** |

5(b)'s target is 3 of 3 across three *different* kinds of empty, so a try there
means a query rather than a pass. That path never calls the model, so all five
passes should come out identical. `score.py` checks that instead of assuming it,
and all five passes of all three queries matched.

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

Three steps, and `suggest_outfit` isn't one of them. The run that works takes
eight.

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
`session["search_results"]`. The loop moved past `lst_001` without the session
and the actual call getting out of sync, and that's exactly the failure I wrote
this criterion to catch.

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

Nine results, the most expensive is $38, nothing over the limit. Across all 25
runs that named a price limit, nothing went over.

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

Each one repeats back a filter with its actual value, which is what 5(b) asks
for. The third one also shows up a grammar bug — "To get results, or use words"
— which I've written up under What's Still Broken.

---

## Verdicts and Diagnoses

These are against the targets exactly as I wrote them in unit 3. I revised two
criteria in this unit (`criteria.md`, with the originals left in place above
each revision); both revisions make the criterion *harder*, and I'm not using
either of them for the verdicts here.

| # | Criterion | Target | Verdict | How I decided |
|---|---|---|---|---|
| 1 | A matching query completes all three tools | 4 of 5 | **MET (5/5)** | All five passes over all five matching queries got through `search_listings`, `suggest_outfit` and `create_fit_card` and came back with a real card, not the tool's own "no fit card" string. 25 runs, nothing failed, nothing crashed. |
| 2 | An impossible query stops before the second tool | 5 of 5 | **MET (5/5)** | 5 of 5. `search_results` was empty, there's no `suggest_outfit` step anywhere in the trace, `outfit_suggestion` and `fit_card` were both still `None`, and the message says what to change. I checked the trace rather than the session, so a tool that got called without being recorded would still have been caught. |
| 3 | The item the search found is the item the next tool received | 5 of 5 | **MISSED (4/5)** | Try 1 failed. The three id checks passed on all 25 runs, so the loop never mixed an item up, including on the path where it rejects a candidate and goes round again. What failed is the last part, "the fit card's named item must be that listing's title". 4 of 5 against a 5-of-5 target is a miss. |
| 4 | The fit card names the item, its price and its platform, every time | 5 of 5 | **MET (5/5)** | All 25 cards gave the price as a number, named the platform, and named the item or the kind of clothing it is in the first sentence. All of them were 2–3 sentences and 180–330 characters, against a limit of 2–4 sentences and under 400. And the five openings inside each pass were all different, five times out of five. |
| 5 | A stated price ceiling is never exceeded, and the empty-search message is actionable | (a) 5 of 5, (b) 3 of 3 | **MET (5/5)** | (a) nothing over the price limit across 25 runs and 200-odd returned listings, and my parser found the limit in all five phrasings. (b) all three messages repeat back a filter with its real value, on all five passes. |

**One miss, and it isn't where I thought it would be.** In unit 3 I called
criterion 4 "the criterion most at risk", because 32 of the 40 listings have no
brand and I figured any sentence leaning on the brand would come out as a
fragment. That turned out to be a risk I'd already designed away without
noticing: the caption prompt never passes `brand` at all, and the stylist system
prompt says not to mention a brand unless it's given one. I made a prediction
about a field the prompt doesn't even use, so it couldn't have come true.

### Diagnosis: criterion 3, try 1

**Where it happened:** in what the model wrote. Not the tool, not the branch,
not the session.

**What happened.** On try 1 of the graphic tee scenario, the loop picked
`lst_033` "Vintage Band Tee — Faded Grey" and the caption came back as:

```
Charcoal tour tee with that thin, paper-soft cotton you can't fake. Layer it
over a white tank with loose dark denim for an easy streetwear slouch, or tuck
it into khaki trousers with heavy boots and a cropped jacket. Grab this faded
piece for $19 over on depop before I change my mind.
```

**Why it happened.** That same search also returned `lst_006` "Graphic Tee —
2003 Tour Bootleg Style" and `lst_002` "Y2K Baby Tee — Butterfly Print". Of the
three words in the title of the item that got picked, `tee` belongs to all three
of those listings — only `band` and `grey` belong to `lst_033` by itself. The
caption uses neither of them. It uses `tour`, which belongs to `lst_006` and to
nothing else.

I checked where `tour` came from, because it matters a lot whether the model
read it somewhere or made it up:

```
'tour' in the outfit suggestion passed to create_fit_card:   False
'tour' in any item field the prompt passes:                  False
'tour' in the listing's own description (not passed at all):  False
```

It's in none of them. The model guessed it from the `band tee` style tag, since
band merch is tour merch, and wrote a word that appears nowhere in anything I
sent it. At the same time it dropped `band`, which is the one word in that title
that tells this listing apart from the other two tees on the same page of
results.

So the problem is in the prompt, and in one line of it.
`tools.py::create_fit_card` used to say:

```
- Name the item or what kind of thing it is in the first sentence.
```

That "or what kind of thing it is" is me handing the model permission to reword
things, and it took it. The tool worked. The loop worked. The session was
consistent the whole way through — all three ids agreed on this exact run. What
failed is that the caption, which is the only part of any of this that a user
actually reads, described a different item than the one it was selling them.

**Why I'm calling this a miss and not nitpicking.** This is the one place where
how I read a criterion changes the verdict, so I should show my work. Criterion
3's last part says "the fit card's named item must be that listing's title".
Read completely literally — the card contains the title word for word — that
fails basically every caption anyone has ever written, because "Vintage Band Tee
— Faded Grey" is a listing title, not a sentence. Read loosely — the card shares
any word at all with the title — it passes this card, because `tee` is in there,
and it would just as happily pass a card that was obviously about one of the
other two tees.

Neither of those is usable, so I read it for what I said in `criteria.md` it was
*for*: "an off-by-one there would style candidate *n* while having written
candidate *n+1* into the session ... nothing in the user-facing output would
look wrong". If that's the point, then the question isn't "does the card mention
this item" but "out of the items the search returned, which one is this card
describing?" So the card has to use at least one word that belongs to the chosen
listing and to none of its neighbours, and it mustn't fit a neighbour better.
That's the strictest of the three readings and it's the only one that can
actually catch the bug I said this criterion was there to catch.

Under the loose reading criterion 3 scores **5/5 MET**. Under mine it scores
**4/5 MISSED**. I'm putting both numbers here so the choice is out in the open
rather than buried in a file. I'm going with the strict one.

### The pattern

There's only one miss, so there's no pattern across misses. There is a pattern
across the *near* misses, and it's the one worth pointing at: everything still
weak in this agent is in the caption prompt, and none of it is in the loop.

- Criterion 3 failed because the caption dropped the word that identifies the item.
- Criterion 4 passed, but its "five different openings" part passed *too easily*,
  and a measurement that part doesn't make shows the same prompt producing
  "Scored these perfectly faded black straight-leg jeans on thredUp" word for
  word on two separate tries of the same item.
- Criterion 1 passed, but the thing its 4-of-5 target was justified by is a
  property of `search_listings` that the criterion's own wording rules out.

The loop, both branches, the session and my two no-model tools didn't produce a
single failure in 50 runs. Everything that went wrong, and everything that
nearly went wrong, happened in the one place where a model writes sentences a
person reads.

## Loop Trace

One full run, step by step, with the MCP call showing up at step 2. Both traces
are copied straight out of the recorded test run in `results/` — I didn't re-run
them to make them look nicer for the write-up. The `trace.step()` calls are in
`agent.py::run_agent` and the formatting is `trace.py`.

**A run that works** — scenario "bottoms — jeans", try 2. This is the one that
uses my second branch: candidate 1 comes out overpriced, gets rejected, and the
loop goes round again.

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

Step 2 is the MCP call. Steps 3 to 5 are the loop actually deciding something
rather than a script running top to bottom — how many times it goes round
depends on the data, because `lst_001` had to get rejected before it could reach
`lst_037`. Step 7 reads its input back *out of* the session instead of reusing
the loop variable, and that's the only reason criterion 3 can be checked at
all.

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

Three steps instead of eight, and neither of the tools that call the model shows
up. The two traces being different lengths is how I know the branch works.

**On the MCP move.**

What changed in the code: `mcp_server.py` registers `search_listings` with
typed inputs — `description: str` required, `size: str | None` and
`max_price: float | None` optional — which is what FastMCP builds the published
schema from. `agent.py` no longer imports `search_listings` from `tools.py` at
all; it calls it by name over stdio through `mcp_client.call_tool`, wrapped in
`agent.py::_search_over_mcp`. The other three tools stay direct calls, so the
seam is visible: one tool crosses a process boundary and three do not.

Writing the description was the part that wasn't code. It's aimed at somebody
whose agent will never see my `tools.py`, so it has to carry everything the Tool
Inventory used to carry for me: that `max_price` means "or cheaper" and is in
whole dollars, that the sizes come in four kinds that don't compare and a
listing only matches inside its own kind, that `brand` is null on 32 of the 40
listings, and that an empty list means "nothing in stock for this" rather than
an error. Last unit the empty case was a note to myself. Here it's a promise to
someone else.

When I compared the inputs against my README I expected to find a mismatch and
didn't — the types in my Tool Inventory and the type hints in the code already
agreed.

**Did anything behave differently?** No, and I checked rather than assuming.
Direct call and MCP call, same arguments, diffed:

```
direct : type list len 10
mcp    : type list len 10
equal  : True

empty case over MCP: []
```

Exactly the same, right down to the empty list. That isn't automatic, and the
reason is in `mcp_client._unwrap`: MCP hands things back as content blocks, so
without that step my loop would have started getting a string where it used to
get a list. Then `if not session["search_results"]` would have been checking
whether a non-empty string is empty, and my branch would have quietly stopped
firing without ever erroring.

What *did* change is the number of ways this can break. A function call can't
fail to be reached; a separate program can. `_search_over_mcp` raises
`SearchUnavailable` both when it can't reach the server and when it gets back
something that isn't a list. That second check matters more than it looks:
`None` counts as empty in Python, so a broken connection that returned nothing
would have been read by my empty-search branch as "nothing in the catalogue
matches" and told the user that as though it were a real shopping result. That
way of failing didn't exist last unit, and it's the one thing the MCP move made
worse.

---

## Failure Modes, Triggered on Purpose

Four of them, not three — the three the assignment names, plus the one that came
with the MCP move. I triggered each one on purpose instead of waiting to run
into it, and every message below is the real text copied out of my terminal.

The test I used on each message is the one from the assignment: could somebody
who can't see my code read this and know what to do next? Two of the four
already passed that. One had a fine message but failed at everything around the
message. One didn't exist last unit.

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

This comes from `agent.py::_no_results_message`. It lists all three filters with
their real values and then names three specific things you could change, so
there's something to actually do without reading any of my code. I didn't add a
handler for this one.

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

This comes from the empty-wardrobe branch of `tools.py::suggest_outfit`. It's
advice, not a crash and not a blank string, and the first line explains why the
advice is general instead of leaving the user to work that out. The run still
finishes and still writes a fit card. I didn't add a handler for this one
either.

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

Two problems, and neither of them is the wording.

The trace stops at step 4. The run went wrong at step 5, and step 5 isn't in the
trace at all — the one thing a trace exists to show me was missing at exactly
the moment I needed it. That's worse than a bad message, because a bad message
at least tells you something happened.

And my agent had already found a $22 Crochet Halter Top and checked its price as
fair. Search and `compare_prices` don't call the model, so both of those are
things I actually know, not guesses. They got thrown away with the error,
because the only thing catching `ModelUnavailable` was the catch-all
`except Exception` in `app.py::main`, and that has no access to the session.

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

Now the failure is its own trace step, and the half of the run that doesn't need
the model survives it. I put my key back straight afterwards. `git diff` on
`.env` is empty because `.env` is gitignored, so this section is the only record
that I ever broke it.

The same handler catches `QuotaGuard`. It's a different cause with the same
shape — the model call didn't happen — and it would have hidden the session in
exactly the same way.

**Then it caught a real one that I didn't set up.** On my last check before
submitting, the service came back with an actual 503:

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

Completely different cause from the bad key — nothing to do with the user and
nothing they can fix — and the handler I wrote for the bad key carried it
anyway, because it reports what broke and what survived instead of guessing why.
The one line that's wrong here is "fix the key or the connection", which is bad
advice when the server is just down; the right thing to do is wait. If I wrote
this handler again I'd split that last line depending on whether the problem was
the key or the service being unavailable.

### 4. MCP server unreachable — the failure mode the move introduced

This one didn't exist last unit. Before Milestone 1, a broken search was just an
error inside my own program. Now it's a separate program that might not start,
a connection that might not go through, and a tool name that might not be
registered. I triggered it by pointing `mcp_client.SERVER` at a file that isn't
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

This comes from `agent.py::_search_over_mcp`. The error MCP gives you on its own
("unhandled errors in a TaskGroup") is useless by itself, which is exactly why
my handler names two commands that find the real problem instead of just
reprinting that and giving up.

`_search_over_mcp` also raises `SearchUnavailable` when the server sends back
something that isn't a list. That matters more than it looks. My first branch
decides what to do by checking whether `search_results` is empty, and `None`
counts as empty in Python, so a broken connection that returned nothing would
have been read as "nothing in stock matches your query" and shown to the user
as a real result. A broken connection and an empty closet can't be allowed to
look the same to that branch.

---

## The Improvement

**What I'm adding from the stretch list**, said up front: I did *not* move a
second tool onto MCP and I did *not* add retry-with-looser-constraints. I did
add **a second fix from my diagnosis, measured the same way as the first**.
So there are three run logs below: before, after one change, and after two.

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

**Which failure I was trying to fix.** My only miss: criterion 3, try 1, where
the caption for `lst_033` said "Charcoal tour tee". My diagnosis blamed the
phrase "or what kind of thing it is", which gives the model permission to do
exactly the rewording that lost the identifying word. This is the "rewrite one
prompt" option from the list, and it's the one my diagnosis pointed at rather
than the one that would have been easiest.

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

**Did it help?** It did exactly what I aimed it at, and it made my agent worse
overall. Criterion 3 went from MISSED to MET and hasn't failed since. Criterion
4 went from a clean 5 of 5 to 0 of 5.

Here's why it broke, because "it broke" isn't a diagnosis either. The price
stopped being a number and started being a word:

```
try 1: Scored these thrashed Straight Leg Black Jeans — Faded for thirty bucks
       on thredUp and haven't taken them off since.
try 2: ... Scored off thredUp for thirty bucks, they have the kind of slouchy,
       grunge weight ...
try 3: Scored this perfectly faded vintage band tee over on depop for nineteen
       bucks.
```

Five of the 25 cards lost the digits. None of them gave a *wrong* price —
"thirty bucks" for a $30 item is true — but criterion 4 asks for the price as a
number, and I asked for that because a spelled-out price stops being true the
moment a listing isn't a round number of dollars.

Those five failures land one per try, four on the jeans and one on the tee, so
every single try has a bad card in it and the criterion scores 0 of 5. That
spread is worth noticing by itself: when I check a whole set of five at once and
require all of them to pass, a problem that only hits 20% of cards fails the
criterion completely. Which is what I meant by "every card", so this is the
check working, not the check being unfair.

Why my change caused it is partly me guessing, and I'd rather say so than
pretend otherwise. What I know for sure is that I never touched the price rule,
and that the old rule — "State the price ($30) exactly once" — shows the digits
without ever saying the digits are the actual requirement, so "thirty bucks"
always satisfied it as written. What changed around it is that my new naming
rule is long, insistent about copying the listing's own words, and makes the
first sentence stiffer. My guess is the model got more casual elsewhere in the
sentence to make up for that. The rule could always be satisfied with words; my
first fix is just what made the model start doing it.

One more side effect that none of my criteria measure: the title rule is being
followed so literally now that some cards paste the raw listing title into the
sentence, em dash and all — "these thrashed Straight Leg Black Jeans — Faded for
thirty bucks". That reads like a database field dropped into a sentence.

### Improvement 2 — fixing what the first one broke (stretch)

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

**Which failure I was trying to fix.** Criterion 4's 0 of 5, and nothing else. I
left the naming rule from the first fix exactly as it was, because criterion 3
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

**Did it help?** Yes, a lot, and still not enough. The problem I aimed at went
from 5 cards in 25 down to 1 in 25:

| | Before | After 1 | After 2 |
|---|---|---|---|
| Cards with no numeric price | **0 of 25** | **5 of 25** | **1 of 25** |
| Criterion 4 | MET (5/5) | MISSED (0/5) | MISSED (4/5) |

Cutting the problem by 80% moves the criterion from 0 of 5 to 4 of 5 and no
further, because criterion 4 says *every* card. One bad card fails its whole
try, so the single one left over — one card in 25 — costs me a full try. It's
the same mistake in the same form, just on a different item:

```
accessories — shoulder bag, try 5, price $38:
That classic Mini Shoulder Bag in tan leather is thirty-eight dollars over on
poshmark. It's the easiest way to pull together a slouchy grey sweatshirt and
wide khakis without looking like you tried too hard.
```

"thirty-eight dollars", under a rule that says in plain words "in digits with
the dollar sign, written exactly as \"$38\" — not spelled out in words". There's
nothing ambiguous about that instruction. It gets followed 24 times out of 25,
and at temperature 0.9 it gets ignored once.

That's the real finding here, and I think it's worth more than the fix itself:
**if I need an exact string in what the model writes, asking more firmly doesn't
make it reliable.** Three versions of that one rule gave me failure rates of 0%,
20% and 4%, and none of them got to 0% because of how well I worded it — the 0%
in my before-run was luck on an easier version, since the old rule could be
satisfied with words too and the model just hadn't done it yet.

### Where the agent ended up

| Criterion | Before | After 1 | After 2 | Net |
|---|---|---|---|---|
| 1. Completes all three tools | MET (5/5) | MET (5/5) | MET (5/5) | — |
| 2. Impossible query stops early | MET (5/5) | MET (5/5) | MET (5/5) | — |
| 3. Item found is item received | **MISSED (4/5)** | MET (5/5) | **MET (5/5)** | **fixed** |
| 4. Card names item, price, platform | MET (5/5) | MISSED (0/5) | **MISSED (4/5)** | **broken** |
| 5. Ceiling held, empty message actionable | MET (5/5) | MET (5/5) | MET (5/5) | — |

**The honest summary: I traded one miss for another.** My agent started this
unit missing one of five criteria and it ends the unit missing one of five
criteria, at the same 4-of-5 rate, just somewhere else. Criterion 3 is fixed and
hasn't failed in 50 runs since. Criterion 4 got broken as a side effect of
fixing it, and my second change got back most of what the first change cost but
not all of it.

I'm not undoing either change, and the reason is in the numbers rather than a
preference. Criterion 3's failure showed a user a caption describing a different
item than the one it was selling them. Criterion 4's leftover failure shows a
user "thirty-eight dollars" instead of "$38", which is true and just casual — it
would only become a real problem on a listing whose price isn't a round number,
and my data doesn't have any of those. If I have to carry one miss, that's the
one I'd pick. But it's still a miss against a target I set for myself, I'm
reporting it as one, and the thing that would actually close it is to stop
asking the model for the facts at all, which is problem 1 under What's Still
Broken.

---

## What's Still Broken

One criterion is still missed: **criterion 4, at 4 of 5 against a target of 5 of
5**, because one card in 25 writes "thirty-eight dollars" instead of "$38". That
and five other things, in the order I think they matter rather than how easy
they'd be.

**1. Criterion 4 can't be closed by writing a better instruction, and that's the
real thing I learned this unit.**

Three versions of one prompt rule gave me three failure rates — 0%, 20%, 4% —
and the only one that hit zero got there by luck rather than by being clear. My
original rule, "State the price ($30) exactly once", could be satisfied with
words all along; the model just hadn't tried that yet. The rule I've ended up
with says "in digits with the dollar sign, written exactly as $38 — not spelled
out in words", and it still gets ignored once in every 25 cards at temperature
0.9. Asking more firmly isn't a mechanism, it's a hope with a measured success
rate of 96%.

Fifty runs before, fifty after, fifty after that — 150 runs — and between them
the loop, both branches, the session, `search_listings` and `compare_prices`
produced zero failures. Every single miss this unit came out of
`create_fit_card`. That one prompt now carries a rule about copying the title's
words, a rule about writing the price in digits, and a rule about not sounding
like a product page, and the first two pull against the third. My first fix is a
worked example of that: I tightened one thing and loosened another somewhere I
wasn't looking.

What I'd do, and it's the first thing I'd do next unit: stop asking the model
for the facts at all. The price and the platform are strings I already have. A
caption that has to contain them exactly is a caption with a blank in it, not
something a model at temperature 0.9 should be trusted to copy out. I'd have
`create_fit_card` write only the description and then build the sentence with
the price and platform in Python. That turns criterion 4's price and platform
parts from things I *check* into things that can't fail, and it lets those three
fighting rules drop back down to one.

Why I stopped here instead: that changes what the tool hands back, not just a
prompt, and the rule for this unit is the MCP move plus one improvement. I spent
the improvement on what my diagnosis actually named and the stretch allowance on
the problem that caused. Taking a third go would have meant three changes
between my first run and my last, and then I couldn't honestly say which change
did what — which is the one thing this unit is actually measuring.

**2. Criterion 4's "five different openings" part couldn't fail, and the thing it
was written to catch is happening.**

I revised this in `criteria.md` and left the original in place. The part compared
openings across five *different* garments, which is nearly impossible to fail —
a card about a leather belt and a card about platform mary janes aren't going to
start the same way, because the items have no words in common. It passed 5 of 5
and told me nothing.

Measured the way I actually meant it, with one item captioned over and over,
`lst_037` gives 4 of 5 different openings, and "Scored these perfectly faded
black straight-leg jeans on thredUp" shows up word for word on two separate
tries. If I only compare the first four words it's 3 of 5. The mail merge I
wrote that part to prevent is partly already here.

Why I stopped: the revision *is* the finding. Measuring it properly needs the
same item run five times as its own scenario, and acting on it means adding a
fourth rule to a prompt that already has three too many — which is problem 1,
and that's where it should get fixed, not patched here.

**3. Criterion 1's target rests on something criterion 1 can't measure.**

Also revised, original left in place. I justified the 4-of-5 target with "roughly
one query in five that a human would call reasonable" finding nothing, but the
criterion starts with "given a query that matches at least one listing" — so the
failure I picked the number for is ruled out by the criterion's own wording.
`probe_synonyms.py` measures it directly, and my original guess was close and
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

The two that get results without getting the right item are the worse half: the
user gets styled something they never asked about and nothing tells them that
happened. None of my criteria catch that, and even my revised version only
catches the zero-results kind.

What I'd do: a small synonym table mapping the obvious pairs onto the words my
data actually uses — about a dozen entries would cover all four of these. I
didn't, because that changes `search_listings`, which is the tool I just
published over MCP, and changing how a tool behaves in the same unit I promised
somebody what it does is the wrong order to do things in.

**4. The empty-search message has a grammar bug when the query has keywords but
no other filters.**

```
Nothing in the 40 listings matches all of: keywords: sequined, ballgown.
  To get results, or use words closer to how a seller would title it — ...
```

"To get results, or use words" — that dangling "or" happens because
`agent.py::_no_results_message` builds its list of suggestions conditionally,
and when there's no price limit and no size, the last "or ..." ends up leading
the sentence. It still passes criterion 5(b), which only asks that a filter gets
repeated back with its value, and it's a one-line fix in how I build that list.
But it's also the first thing a user sees when their words aren't in my data,
which is the most common way this agent fails anyone. I didn't fix it because
it's not what my diagnosis named and this unit allows one change. It's a
two-minute job next unit.

**5. `MAX_ITERATIONS` has never actually been reached, so my stop condition is
untested.**

`trace.check_iterations` gets called every time round the loop and the limit is
10, but the biggest result set in any of these 150 runs was 10 items, and the
loop breaks as soon as one candidate isn't overpriced. The mary janes scenario
is the closest I get — every candidate overpriced — and it only has one result.
The guard has never fired, so I don't actually know it works. Forcing it would
need a scenario with more than 10 overpriced candidates in one category, and 40
rows of data can't produce that.

**6. Nothing checks that the outfit only names clothes the user owns.**

`suggest_outfit`'s prompt says "Do not suggest anything they do not own" and I
never verify it. The wardrobe is a list of names I already have, so this is
easy to check mechanically, and it's the obvious sixth criterion. It isn't a
miss, because I never wrote it down as a target — which is the honest reason
it's down here instead of in the table.

---

### If I missed nothing, were my targets too low?

I missed one of five, but the question is still worth answering, and the answer
is that two of them were too low in a specific way. Criteria 2 and 5(a) are both
pure no-model paths — one `if` on the length of a list, one `<=` on a number
I already parsed — and both came out 5 of 5 across all 150 runs. That isn't an
agent passing a test, that's arithmetic. I set them at 5 of 5 deliberately,
reasoning that "a flaky result here would be information", and that reasoning
does hold up: they cost nothing to keep checking and they would have screamed
if the MCP move had changed what search gives back. But they were never going to
tell me anything about the parts of this system that can actually vary.

The criterion I'd tighten is 4, and the revision in `criteria.md` is me
tightening it. Criteria 1 and 2 were given to me. Of the three I wrote myself,
criterion 3 is the one that earned its place — it's the only one that found
anything, and it found it in a part of the run I wouldn't have thought to look
at, because I wrote it to catch a bug in my loop and it caught a bug in my
captions instead.

## How I Used AI — Unit 4

Continues the unit 3 section above, and the same split applies.

**AI inside the app.** Unchanged from unit 3 — `suggest_outfit` and
`create_fit_card` call the model, `search_listings` and `compare_prices` don't.
That mattered more this unit than last, because it's the reason the test is
affordable. My five criteria need 50 runs each time I measure them, and only 25
of those 50 touch the model, so a full run costs about 60 calls instead of 100.
It's also why I could design the scenario set without spending anything: which
item each query picks is decided by two tools that never call the model, so I
worked all five out ahead of time from the data.

Running with the cache off is what makes five tries five real answers, and it's
also what made the rate limiter show up — the free tier allows 15 requests a
minute and a full run of mine is around 60, so each measurement takes about
fifteen minutes of the limiter pacing me. Three measurements, 182 model calls,
nothing crashed.

**AI as a coding tool.** Same as before: writing Python from things I'd already
decided, plus boilerplate, syntax and debugging. This unit that meant the
FastMCP registration block, the string-matching helpers in `score.py`, and the
JSON dump I added to `run_eval.py` so a program could read my results instead
of me reading 50 runs by eye.

What stayed mine: the five criteria and their targets (written in unit 3, before
any results existed, and the commit history shows that), which scenarios to run
and why, how to read each criterion when its wording needed a decision, the
verdicts, and the diagnosis of the miss. The judgement calls in this unit are
the graded part and they're the part I did.

**Two things I'd point at as the actual work of this unit:**

*Testing my own checker.* `score.py` came back MET on all five criteria the
first time, and a checker that can't fail isn't evidence of anything. So I built
nine runs that I broke on purpose — a blanked fit card, a branch that walks past
itself, an off-by-one in the trace ids, a card describing the wrong candidate, a
missing platform, a missing price, five identical openings, a result over the
price limit, an unhelpful empty message — and fed them through. It caught eight.
The one it missed was a real bug in my own matching: I was comparing title words
as pieces of words rather than whole words, so "hat" inside "that" counted as
naming a bucket hat, and "tee" — which three candidates in one search result
share — identified none of them. Fixing that is what turned criterion 3 from MET
to MISSED. The only miss in this unit came out of testing the test, and without
it my whole run would have been a clean sweep produced by a checker that
couldn't return FAIL.

*Checking the reasoning behind a target, not just the target.* My criterion 1
target of 4 of 5 was justified in unit 3 by a guess that roughly one reasonable
phrasing in five would find nothing. The clause as I wrote it can't actually
measure that, because it starts "given a query that matches at least one
listing". So I wrote `probe_synonyms.py` to measure the guess directly: 4 of 15
alternative phrasings (27%) fail to find the garment the seller's own wording
finds, against the 20% I'd predicted. The guess was sound and slightly
optimistic, and that's now its own clause in `criteria.md` with its own number.

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
