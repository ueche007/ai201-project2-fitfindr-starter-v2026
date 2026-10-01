# Milestone 1 — what's actually in the data

Read before writing any tool. 40 listings in `data/listings.json`, 10 wardrobe
items in `data/wardrobe_schema.json`.

## Listing fields

| Field | Type | Example | Useful for |
|---|---|---|---|
| `id` | str | `lst_002` | identity checks in the session |
| `title` | str | `Y2K Baby Tee — Butterfly Print` | keyword match (weight it highest) |
| `description` | str | `Super cute early 2000s baby tee…` | keyword match (weak) |
| `category` | str | `tops` | keyword match, and comparables for price |
| `style_tags` | list[str] | `['y2k','vintage','graphic tee','cottagecore']` | keyword match (strong) |
| `size` | str | `S/M` | size filter — see below |
| `condition` | str | `good` | not filtered on this unit |
| `price` | float | `18.0` | price ceiling, price comparison |
| `colors` | list[str] | `['white','pink','purple']` | keyword match (weak) |
| `brand` | str or **None** | `null` | keyword match — **32 of 40 are None** |
| `platform` | str | `depop` | printed in the fit card |

## Wardrobe item fields

`id`, `name`, `category`, `colors`, `style_tags`, `notes` (str **or None**).

An empty wardrobe is `{"items": []}` — same shape as the example, `items` just
has nothing in it. `get_empty_wardrobe()` strips the `_note` documentation key,
so both wardrobes come back identical in shape.

## The size problem

Sizes are not one scale. All 22 distinct values, grouped:

- **Letter** — `S`, `M`, `L`, `XL`, and the ranges `S/M`, `M/L`, `L/XL`
- **Letter with a parenthetical** — `XL (oversized)`, `XL (fits oversized)`
- **Waist** — `W27`, `W28`, `W29`, `W30`, `W32`, `W30 L30`
- **Shoe** — `US 7`, `US 8`, `US 8.5`, `US 9`
- **One size** — `One Size`, `One Size (adjustable)`, `One Size / Oversized`

Which is why a plain substring test is wrong, exactly as the docstring warns:

- `"s" in "us 9"` → True, so asking for a small top returns shoes
- `"l" in "xl"` → True, so asking for L returns XL
- `"m" in "medium wash"` would hit if I tested against the title

**Decision:** classify both the requested size and the listing size into a
family (letter / waist / shoe / one-size), and only match within a family.
`One Size*` matches any request. Letter ranges split on `/` into a token set,
so `S/M` satisfies a request for `S` or `M`. Parentheticals are stripped before
tokenising. A bare number is read as shoe size when ≤ 16 and waist above that.

## Price range

$12 to $75. Median around $27.50. Useful consequences:

- `under $30` keeps 23 of 40 listings — a real filter, not a no-op
- `under $5` keeps nothing, which is what makes the empty-search branch testable
- Enough density in the $14–$38 band to compare an item against comparables

## Category and size, cross-referenced

```
accessories : One Size, One Size (adjustable)
bottoms     : M, M/L, S, W27, W28, W29, W30, W30 L30, W32
outerwear   : L, M, M/L, S
shoes       : US 7, US 8, US 8.5, US 9
tops        : L, L/XL, M, One Size / Oversized, S/M, XL, XL (fits oversized), XL (oversized)
```

`bottoms` carries both letter and waist sizes, so the family rule has to be
driven by the size string itself, not by the category.

## Platforms and condition

`depop` 18, `thredUp` 11, `poshmark` 11. Condition: `good` 19, `excellent` 17,
`fair` 4.
