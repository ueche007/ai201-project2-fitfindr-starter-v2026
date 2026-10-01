"""
Style memory — the wardrobe, persisted between runs. (Stretch feature.)

Without this, every run styles against the same fixed example wardrobe and the
agent cannot learn anything. With it, an item found in one run can be worn in
the next:

    python app.py ask 'vintage graphic tee under $30' --remember
    python app.py ask 'baggy jeans under $40'          # the tee is now owned

The file lives at data/style_memory.json and holds a wardrobe in exactly the
shape data/wardrobe_schema.json describes — a dict with an `items` key — so
suggest_outfit cannot tell the difference between a remembered wardrobe and the
example one. That sameness is the point: style memory adds persistence without
adding a second wardrobe format for the tools to handle.

It is deliberately NOT in git. It is per-user state that changes on every run
with --remember, and committing it would mean every run showed up as a diff.
"""

import json

import config
from utils.data_loader import get_example_wardrobe

MEMORY_PATH = config.DATA_DIR / "style_memory.json"


def _money(price) -> str:
    """Prices are whole-dollar floats, so str() would give "$19.0"."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return "?"
    return f"{value:.0f}" if value == int(value) else f"{value:.2f}"


def has_memory() -> bool:
    """True when a wardrobe has been saved before."""
    return MEMORY_PATH.exists()


def load_wardrobe() -> dict:
    """
    The remembered wardrobe, or the example one when nothing is remembered yet.

    Returns:
        A wardrobe dict with an `items` key holding a list of wardrobe items.
        Falls back to the example wardrobe when the file is absent, and to an
        empty wardrobe when it is present but unreadable — a corrupt memory
        file should not take the agent down with it, and an empty wardrobe is a
        case suggest_outfit already handles.
    """
    if not MEMORY_PATH.exists():
        return get_example_wardrobe()
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        return {"items": []}
    return {"items": items}


def save_wardrobe(wardrobe: dict) -> int:
    """
    Write a wardrobe to the memory file.

    Returns:
        How many items were saved.
    """
    items = (wardrobe or {}).get("items") or []
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(
        json.dumps({"items": items}, indent=2), encoding="utf-8"
    )
    return len(items)


def listing_to_wardrobe_item(listing: dict) -> dict:
    """
    Turn a listing dict into a wardrobe item dict.

    The two shapes are close but not the same: a wardrobe item has `name` where
    a listing has `title`, and has no price, platform, size or condition. What
    would otherwise be lost goes into `notes`, which is where the schema says
    free text about how a piece fits or is worn belongs.

    The id is prefixed rather than reused so a remembered item can always be
    traced back to the listing it came from, and so it cannot collide with the
    example wardrobe's own w_001…w_010.
    """
    return {
        "id": f"w_{listing.get('id', 'unknown')}",
        "name": listing.get("title", "unnamed item"),
        "category": listing.get("category", "other"),
        "colors": list(listing.get("colors") or []),
        "style_tags": list(listing.get("style_tags") or []),
        "notes": (
            f"Thrifted from {listing.get('platform', 'unknown')} for "
            f"${_money(listing.get('price'))}, size {listing.get('size', '?')}"
        ),
    }


def remember_item(listing: dict) -> tuple[dict, bool]:
    """
    Add one found listing to the remembered wardrobe.

    Starts from the example wardrobe the first time, so a user's first
    remembered find joins a plausible closet rather than an empty one.

    Returns:
        (the updated wardrobe, True if it was newly added). Already-remembered
        items are not duplicated, and the flag is False in that case so the
        caller can say so rather than claiming a save that changed nothing.
    """
    wardrobe = load_wardrobe()
    new_item = listing_to_wardrobe_item(listing)

    if any(existing.get("id") == new_item["id"] for existing in wardrobe["items"]):
        return wardrobe, False

    wardrobe["items"].append(new_item)
    save_wardrobe(wardrobe)
    return wardrobe, True


def forget_all() -> bool:
    """
    Delete the memory file, so the next run falls back to the example wardrobe.

    Returns:
        True if a file was deleted, False if there was nothing to delete.
    """
    if not MEMORY_PATH.exists():
        return False
    MEMORY_PATH.unlink()
    return True
