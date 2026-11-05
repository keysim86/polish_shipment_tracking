"""Persistent list of shipments the user chose to ignore."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.ignored"
SAVE_DELAY = 10

# An ignored shipment is forgotten once an account that used to return it has
# kept answering without it for this long. Not instantly: an account can
# answer "no shipments" by mistake for hours (a disabled DPD user returns an
# empty list until its 12h token expires), and dropping the entry then would
# resurrect the shipment as soon as the account recovers.
ABSENT_GRACE_SECONDS = 24 * 3600
# Backstop for entries no account can vouch for any more (account removed,
# or ignored before any account returned it).
PRUNE_AFTER_SECONDS = 30 * 24 * 3600
# Persisting "still seen" on every 15-min poll would be pointless disk churn.
SEEN_WRITE_INTERVAL_SECONDS = 6 * 3600
# Upper bound on the list size. Any user can ignore any number, so above it the
# oldest entries no account returns (no sources) are dropped first. Entries
# with sources hide a shipment an account still returns and are never dropped.
# 100 entries keep the ignored_shipments attribute small for every frontend.
MAX_ENTRIES = 100
# Bounds of a stored key (normalized tracking number), as the services accept.
KEY_MIN_LENGTH = 4
KEY_MAX_LENGTH = 64


def normalize_tracking_number(value: Any) -> str:
    """Return the courier-agnostic key for a tracking number."""
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def is_valid_key(key: str) -> bool:
    """Return True for a key the services accept and the list keeps.

    Real tracking numbers are ASCII; the same rule is applied on input and when
    the stored list is loaded, so a stored entry can always be un-ignored.
    """
    return key.isascii() and KEY_MIN_LENGTH <= len(key) <= KEY_MAX_LENGTH


class IgnoredShipments:
    """Ignore list shared by all accounts and couriers.

    Keyed by the normalized tracking number only, so ignoring a shipment hides
    it on every account that sees it, including its Allegro copy.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._items: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        """Load the list from storage and drop long-gone shipments."""
        data = await self._store.async_load()
        items = (data or {}).get("ignored")
        # Older versions stored the caller's raw string (of any length) as the
        # tracking_number: keep only valid entries, keyed and shown normalized.
        self._items = {}
        cleaned = False
        for key, item in (items.items() if isinstance(items, dict) else ()):
            norm = normalize_tracking_number(key)
            if not isinstance(item, dict) or not is_valid_key(norm) or norm in self._items:
                cleaned = True
                continue
            if norm != key or item.get("tracking_number") != norm:
                cleaned = True
            self._items[norm] = {**item, "tracking_number": norm}
        if self._prune() or cleaned:
            self._schedule_save()

    def is_ignored(self, tracking_number: Any) -> bool:
        return normalize_tracking_number(tracking_number) in self._items

    @callback
    def async_reconcile(self, entry_id: str, returned: set[str]) -> None:
        """Update the list from one account's successful fetch.

        `returned` holds the normalized numbers of the active shipments the
        account just returned. An ignored shipment this account used to return
        and no longer does is forgotten after ABSENT_GRACE_SECONDS; another
        account still returning it keeps it on the list.
        """
        now = time.time()
        save = False
        forgotten = []
        for key, item in self._items.items():
            sources = item.setdefault("sources", [])
            if key in returned:
                if entry_id not in sources:
                    sources.append(entry_id)
                    save = True
                if item.pop("absent_since", None) is not None:
                    save = True
                if now - item.get("last_seen", 0) >= SEEN_WRITE_INTERVAL_SECONDS:
                    item["last_seen"] = now
                    save = True
            elif entry_id in sources:
                if "absent_since" not in item:
                    item["absent_since"] = now
                    save = True
                elif now - item["absent_since"] >= ABSENT_GRACE_SECONDS:
                    forgotten.append(key)
        for key in forgotten:
            del self._items[key]
        if self._prune() or forgotten:
            self._changed()
        elif save:
            self._schedule_save()

    @callback
    def async_ignore(
        self,
        tracking_number: Any,
        courier: str | None = None,
        sources: list[str] | None = None,
    ) -> bool:
        """Add a shipment to the list. Return False if it was not added.

        `sources` are the config entries currently returning the shipment.
        It is not added when already there, or when it has no sources and the
        list is full of entries that have them (see MAX_ENTRIES).
        """
        key = normalize_tracking_number(tracking_number)
        if not key or key in self._items:
            return False
        now = time.time()
        self._items[key] = {
            # The normalized number, never the caller's raw string.
            "tracking_number": key,
            "courier": courier,
            "ignored_at": now,
            "last_seen": now,
            "sources": list(sources or []),
        }
        self._prune()
        self._changed()
        return key in self._items

    @callback
    def async_unignore(self, tracking_number: Any) -> bool:
        """Remove a shipment from the list. Return False if it was not there."""
        if self._items.pop(normalize_tracking_number(tracking_number), None) is None:
            return False
        self._changed()
        return True

    def as_list(self) -> list[dict[str, Any]]:
        """Return the list for display, oldest first."""
        return [
            {
                "tracking_number": item.get("tracking_number"),
                "courier": item.get("courier"),
                "ignored_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S%z", time.localtime(item.get("ignored_at", 0))
                ),
            }
            for item in sorted(self._items.values(), key=lambda i: i.get("ignored_at", 0))
        ]

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` whenever a shipment is ignored or un-ignored."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _prune(self) -> bool:
        """Drop long-gone entries, then trim the list to MAX_ENTRIES."""
        cutoff = time.time() - PRUNE_AFTER_SECONDS
        stale = [
            key
            for key, item in self._items.items()
            if item.get("last_seen", item.get("ignored_at", 0)) < cutoff
        ]
        for key in stale:
            del self._items[key]
        excess = len(self._items) - MAX_ENTRIES
        if excess > 0:
            unvouched = sorted(
                (key for key, item in self._items.items() if not item.get("sources")),
                key=lambda k: self._items[k].get("ignored_at", 0),
            )[:excess]
            for key in unvouched:
                del self._items[key]
            stale.extend(unvouched)
        return bool(stale)

    def _changed(self) -> None:
        self._schedule_save()
        for listener in list(self._listeners):
            listener()

    def _schedule_save(self) -> None:
        self._store.async_delay_save(lambda: {"ignored": self._items}, SAVE_DELAY)
