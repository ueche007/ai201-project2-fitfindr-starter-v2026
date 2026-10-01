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
