"""Natural-language rendering of lifecycle histories for external systems.

The renderer turns a typed :class:`~temvera.model.MemoryEvent` history into
deterministic conversational turns and natural-language queries, while keeping
the ground-truth answer separate (computed by the oracle). This lets opaque
external memory systems (which only ingest text) be scored against the same
bitemporal truth as the internal baselines, and removes the "BM25 receives
structured query terms" external-validity gap (E-043).

Rendering is a pure function of the event history: identical inputs produce
byte-identical turns and cases.
"""

from __future__ import annotations

import functools
import re

from dataclasses import dataclass, replace
from datetime import datetime

from .evaluation import QueryCase, cases_from_oracle
from .model import MemoryEvent, Operation

# Distinct, embedding-separable surface names. The synthetic generator emits
# near-identical tokens ("entity-000", "place-38") that collapse under a
# semantic embedder, confounding a bitemporal comparison with an inability to
# tell identifiers apart. `naturalize_events` relabels them via an injective
# map so external LLM/embedding systems are tested on temporal semantics, not
# tokenization. The relabeling is a pure bijection: it leaves the oracle's
# bitemporal logic and every baseline's ranking structurally identical.
_PERSONS = (
    "Mina", "Noah", "Sora", "Liam", "Yuna", "Omar", "Priya", "Kenji",
    "Aisha", "Diego", "Lena", "Tariq", "Freya", "Hugo", "Zara", "Ivan",
    "Maya", "Sven", "Nadia", "Pablo", "Ravi", "Elsa", "Kwame", "Bianca",
    "Toma", "Greta", "Idris", "Wei", "Rosa", "Andre", "Suki", "Bruno",
    "Leyla", "Milo", "Farah", "Otto", "Ines", "Cyrus", "Dalia", "Emre",
)
_CITIES = (
    "Seoul", "Cairo", "Oslo", "Lima", "Accra", "Porto", "Riga", "Perth",
    "Quito", "Nantes", "Cebu", "Split", "Kobe", "Bergen", "Ghent", "Pune",
    "Davao", "Aarhus", "Cuenca", "Turku", "Nagoya", "Leon", "Kumasi", "Bari",
    "Utrecht", "Galway", "Tabriz", "Xian", "Recife", "Nice", "Sapporo", "Graz",
    "Izmir", "Malmo", "Fez", "Linz", "Vigo", "Shiraz", "Bursa", "Trier",
    "Mendoza", "Cork", "Mersin", "Wuxi", "Natal", "Lyon", "Sendai", "Basel",
    "Konya", "Zagreb", "Aba", "Delft", "Almaty", "Faro", "Hue", "Jinan",
    "Ordu", "Breda", "Enugu", "Leiden",
)


# Per-attribute value pools. A single pool (cities) makes every stored fact
# about a subject near-identical text, so cosine retrieval cannot separate
# revisions and the comparison degenerates. Drawing each attribute from a
# different semantic class removes that artifact.
_VALUE_POOLS: dict[str, tuple[str, ...]] = {
    "home city": _CITIES,
    "employer": (
        "Aurora Labs", "Bellwether", "Cobalt Foods", "Dunlin Press", "Everly Bank",
        "Fernwood Clinic", "Granite Freight", "Harlow Studio", "Ionic Systems",
        "Juniper Mills", "Kestrel Air", "Lumen Retail", "Marrow Foundry",
        "Nettle Farms", "Orchid Media", "Pinehall Legal", "Quarry Analytics",
        "Ridgeway Rail", "Sablefish Co", "Thistle Energy",
    ),
    "phone model": (
        "Pixel 7a", "Galaxy S22", "iPhone 13", "Xperia 5", "Nord 3", "Reno 8",
        "Moto G84", "Zenfone 9", "Find X5", "Magic 5", "Edge 40", "Nova 11",
        "Poco F5", "Redmi 12", "Velvet 2", "Aquos R7", "Rog 7", "Mate 50",
        "Vivo V29", "Honor 90",
    ),
    "dietary preference": (
        "pescatarian", "vegan", "low-sodium", "gluten-free", "keto",
        "vegetarian", "halal", "kosher", "dairy-free", "nut-free",
        "high-protein", "low-FODMAP", "paleo", "raw-food", "flexitarian",
        "sugar-free", "soy-free", "shellfish-free", "low-carb", "whole-food",
    ),
    "job title": (
        "radiographer", "site foreman", "sommelier", "actuary", "arborist",
        "cartographer", "luthier", "paralegal", "audiologist", "millwright",
        "epidemiologist", "sound editor", "glazier", "hydrologist", "chandler",
        "typesetter", "farrier", "conservator", "ergonomist", "cooper",
    ),
}
# Synthetic attribute name -> natural attribute name.
_ATTRIBUTE_NAMES = {
    "location": "home city",
    "employer": "employer",
    "device": "phone model",
    "diet": "dietary preference",
    "role": "job title",
}


def _pick(pool: tuple[str, ...], index: int, kind: str) -> str:
    return pool[index] if index < len(pool) else f"{kind}-{index}"


# --- Large pools for scale experiments -------------------------------------
#
# The standard pools above hold 40 names and 20-60 values per attribute, and
# _pick silently falls back to tokens like "Person-102" or "employer-95" past
# them. Those are exactly the synthetic tokens the relabelling exists to avoid,
# and a 2026-10 scale sweep found 19% of values synthetic at 8 entities, 55% at
# 32 and 66% at 128 -- a confound that grew with the variable being studied. The
# large pools are composed from word lists, cover 128 entities with distinct
# values, refuse to fall back, and guarantee that no name or value is a
# substring of any other, because the scorer matches by substring.

_FIRST = (
    "Aisha", "Bruno", "Chen", "Dara", "Elif", "Farah", "Goran", "Hana", "Ingrid",
    "Jonas", "Kofi", "Lena", "Mateo", "Nadia", "Omar", "Priya", "Quinn", "Rosa",
    "Sven", "Tomas", "Uma", "Viktor", "Wen", "Ximena", "Yusuf", "Zara", "Amara",
    "Bjorn", "Carmen", "Dmitri", "Esther", "Felix", "Greta", "Hugo", "Ines",
    "Jamal", "Keiko", "Liam", "Mira", "Nikolai", "Olga", "Pablo", "Rania",
    "Sami", "Tariq", "Valentina", "Wanjiru", "Yara", "Zoltan", "Anika",
)
_LAST = (
    "Okafor", "Brennan", "Lindqvist", "Moreau", "Tanaka", "Haddad", "Novak",
    "Castillo", "Petrov", "Nakamura", "Fischer", "Ramos", "Kowalski", "Achebe",
    "Delgado", "Eriksen", "Fontaine", "Gallagher", "Horvath", "Ibrahim",
    "Jansen", "Kapoor", "Mendoza", "Nwosu", "Pereira", "Quist", "Rahman",
    "Schreiber", "Takahashi", "Ustinov", "Varga", "Whitaker", "Yilmaz", "Zhou",
    "Bianchi", "Coleman", "Dumont", "Esposito", "Farouk", "Garnier",
)
_TOWN_HEAD = (
    "Ash", "Oak", "Elm", "Birch", "Cedar", "Maple", "Willow", "Alder", "Hazel",
    "Rowan", "Thorn", "Fern", "Heath", "Moor", "Brook", "Mill", "Stone", "Iron",
    "Copper", "Silver", "Gold", "Red", "Black", "White", "Green", "North",
    "South", "East", "West", "High", "Kings", "Queens", "Bishops", "Market",
    "Castle", "Bridge", "Dun", "Glen", "Pen", "Wyn",
)
_TOWN_TAIL = (
    "ford", "ton", "field", "bury", "ham", "wick", "dale", "mouth", "worth",
    "stead", "ley", "port", "haven", "minster", "gate", "holm", "thorpe",
    "combe", "cliff", "more", "well", "hurst", "mere", "chester", "brook",
)
_FIRM_HEAD = (
    "Vant", "Corv", "Zenth", "Quil", "Nexo", "Lum", "Oriz", "Pyx", "Solv",
    "Trel", "Brax", "Calt", "Dov", "Elv", "Fyr", "Gal", "Hux", "Jor", "Kest", "Mav",
)
_FIRM_TAIL = ("ara", "ix", "ium", "ora", "eon", "ica", "ent", "ova", "yx", "anta")
_FIRM_KIND = (
    "Analytics", "Logistics", "Health", "Foods", "Robotics", "Capital", "Media",
    "Energy", "Labs", "Biotech", "Mobility", "Studios", "Freight", "Insurance",
)
_PHONE_BRAND = (
    "Galaxy", "Pixel", "Xperia", "Moto", "Nokia", "Redmi", "Zenfone", "Nord",
    "Aquos", "Reno", "Mate", "Vivo",
)
_PHONE_LINE = ("A", "S", "X", "G", "Z", "V")
_SENIORITY = ("Senior", "Junior", "Principal", "Staff", "Associate", "Chief")
_DOMAIN = (
    "Data", "Product", "Platform", "Security", "Cloud", "Mobile", "Brand",
    "Growth", "Payments", "Search", "Network", "Quality", "Research", "Content",
    "Finance", "Clinical",
)
_ROLE = (
    "Engineer", "Analyst", "Manager", "Designer", "Scientist", "Architect",
    "Strategist", "Specialist", "Consultant", "Coordinator",
)
_DIET_HOW = (
    "strictly", "mostly", "seasonally", "weekday", "budget", "locally sourced",
    "high-protein", "low-sugar",
)
_DIET_WHAT = (
    "vegan", "pescatarian", "keto", "paleo", "gluten-free", "dairy-free", "halal",
    "kosher", "low-carb", "Mediterranean", "flexitarian", "nut-free",
)


def _interleave(heads: tuple[str, ...], tails: tuple[str, ...], join: str) -> list[str]:
    """All head/tail combinations, ordered so consecutive picks differ in both."""
    out = []
    for step in range(len(heads) * len(tails)):
        head = heads[step % len(heads)]
        tail = tails[(step // len(heads) + step) % len(tails)]
        out.append(f"{head}{join}{tail}")
    return list(dict.fromkeys(out))


def _containment_free(groups: list[list[str]]) -> list[tuple[str, ...]]:
    """Drop entries that contain another entry, keeping every group's order.

    Entries are visited shortest first, and each is checked by enumerating its
    own substrings against the set of entries already kept: O(n * L^2) rather
    than comparing every pair, which took 95 s at import time when tried. Of a
    conflicting pair the shorter survives; duplicates across groups keep their
    first occurrence.
    """
    owner: dict[str, int] = {}
    for index, group in enumerate(groups):
        for entry in group:
            owner.setdefault(entry.casefold(), index)
    kept: set[str] = set()
    for folded in sorted(owner, key=lambda text: (len(text), text)):
        size = len(folded)
        inner = {folded[i:j] for i in range(size) for j in range(i + 1, size)}
        if not inner & kept:
            kept.add(folded)
    out = []
    for index, group in enumerate(groups):
        out.append(tuple(dict.fromkeys(
            entry for entry in group
            if entry.casefold() in kept and owner[entry.casefold()] == index)))
    return out


@functools.lru_cache(maxsize=1)
def _large_pools() -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Built on first use, not at import: most runs never need them."""
    groups = [
        _interleave(_FIRST, _LAST, " "),
        _interleave(_TOWN_HEAD, _TOWN_TAIL, ""),
        [f"{stem} {kind}" for stem in _interleave(_FIRM_HEAD, _FIRM_TAIL, "")
         for kind in _FIRM_KIND],
        [f"{brand} {line}{number}" for number in range(10, 100)
         for line in _PHONE_LINE for brand in _PHONE_BRAND],
        [f"{a} {d} {r}" for r in _ROLE for d in _DOMAIN for a in _SENIORITY],
        [f"{how} {what}" for what in _DIET_WHAT for how in _DIET_HOW],
    ]
    persons, towns, firms, phones, titles, diets = _containment_free(groups)
    return persons, {
        "home city": towns,
        "employer": firms,
        "phone model": phones,
        "job title": titles,
        "dietary preference": diets,
    }


def _pick_strict(pool: tuple[str, ...], index: int, kind: str) -> str:
    if index >= len(pool):
        raise ValueError(
            f"large {kind} pool exhausted at {index} (holds {len(pool)}); "
            "refusing to fall back to a synthetic token"
        )
    return pool[index]


def naturalize_events(
    events: tuple[MemoryEvent, ...], pools: str = "standard"
) -> tuple[MemoryEvent, ...]:
    """Relabel synthetic subjects/attributes/values to distinct natural names.

    Injective over the distinct tokens actually present, so no two originals
    collapse to one name. Belief and event identifiers are unchanged.
    """
    subjects = sorted({e.subject for e in events if e.subject})
    if pools not in ("standard", "large"):
        raise ValueError(f"unknown pools: {pools}")
    large = pools == "large"
    persons, value_pools = _large_pools() if large else (_PERSONS, _VALUE_POOLS)
    pick = _pick_strict if large else _pick
    subject_map = {name: pick(persons, i, "Person") for i, name in enumerate(subjects)}

    # Values are relabelled per attribute so each attribute draws from its own
    # semantic class. Belief ids carry the attribute, so a value string is
    # resolved through the attribute of the ingest that introduced it.
    attribute_of: dict[str, str] = {}
    for event in events:
        if event.operation is Operation.INGEST and event.value:
            attribute_of.setdefault(event.value, event.attribute or "location")
    value_map: dict[str, str] = {}
    per_attribute: dict[str, int] = {}
    for value in sorted(attribute_of):
        natural = _ATTRIBUTE_NAMES.get(attribute_of[value], "home city")
        pool = value_pools.get(natural, value_pools["home city"] if large else _CITIES)
        index = per_attribute.get(natural, 0)
        per_attribute[natural] = index + 1
        value_map[value] = pick(pool, index, natural.replace(" ", "-"))
    out: list[MemoryEvent] = []
    for event in events:
        out.append(
            replace(
                event,
                subject=subject_map.get(event.subject, event.subject)
                if event.subject
                else event.subject,
                value=value_map.get(event.value, event.value)
                if event.value
                else event.value,
                attribute=_ATTRIBUTE_NAMES.get(event.attribute, event.attribute)
                if event.attribute
                else event.attribute,
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class WorkloadTurn:
    """One natural-language statement derived from a single lifecycle event."""

    recorded_at: datetime
    text: str
    event_id: str


@dataclass(frozen=True, slots=True)
class NLQueryCase:
    """A natural-language query paired with value-level ground truth.

    External systems answer in free text, so truth is expressed as the set of
    belief *values* that a correct answer must contain (``expected_values``) and
    the superseded/deleted values a correct answer must avoid (``stale_values``).
    This mirrors ForgetEval's deterministic substring scoring (E-013).
    """

    case_id: str
    query_text: str
    subject: str
    attribute: str
    valid_at: datetime
    transaction_at: datetime
    expected_values: frozenset[str]
    stale_values: frozenset[str]
    category: str


def _ingest_by_belief(events: tuple[MemoryEvent, ...]) -> dict[str, MemoryEvent]:
    return {
        event.belief_id: event
        for event in events
        if event.operation is Operation.INGEST
    }


def _day(moment: datetime) -> str:
    return moment.date().isoformat()


def render_turns(events: tuple[MemoryEvent, ...]) -> tuple[WorkloadTurn, ...]:
    """Render each event as one deterministic natural-language turn."""
    ingests = _ingest_by_belief(events)
    turns: list[WorkloadTurn] = []
    for event in events:
        ingest = ingests.get(event.belief_id)
        subject = event.subject or (ingest.subject if ingest else event.belief_id)
        attribute = event.attribute or (ingest.attribute if ingest else "value")
        value = event.value or (ingest.value if ingest else "")
        if event.operation is Operation.INGEST:
            text = (
                f"[recorded {_day(event.recorded_at)}] {subject}'s {attribute} "
                f"is {value}, valid from {_day(event.valid_from)}."
            )
        elif event.operation is Operation.RECONFIRM:
            text = (
                f"[recorded {_day(event.recorded_at)}] Confirmed that {subject}'s "
                f"{attribute} is still {value}."
            )
        elif event.operation is Operation.SUPERSEDE:
            valid_from = event.valid_from or event.recorded_at
            text = (
                f"[recorded {_day(event.recorded_at)}] Update: {subject}'s "
                f"{attribute} is now {value} as of {_day(valid_from)}, "
                f"replacing the previous value."
            )
        elif event.operation is Operation.EXPIRE:
            boundary = event.valid_to or event.valid_from or event.recorded_at
            text = (
                f"[recorded {_day(event.recorded_at)}] {subject}'s {attribute} "
                f"({value}) is no longer valid after {_day(boundary)}."
            )
        elif event.operation is Operation.PURGE:
            # The deletion instruction must NOT restate the payload: a system
            # that stores its input verbatim would otherwise be scored as
            # retaining the very value it was asked to delete.
            text = (
                f"[recorded {_day(event.recorded_at)}] Permanently delete "
                f"everything you recorded about {subject}'s {attribute}."
            )
        else:  # pragma: no cover - Operation is exhaustive
            raise ValueError(f"unhandled operation: {event.operation}")
        turns.append(
            WorkloadTurn(
                recorded_at=event.recorded_at, text=text, event_id=event.event_id
            )
        )
    return tuple(turns)


def render_query(case: QueryCase) -> str:
    """Render a bitemporal query case as a natural-language question."""
    return (
        f"What is {case.subject}'s {case.attribute} as of {_day(case.valid_at)}, "
        f"based only on what was known by {_day(case.transaction_at)}?"
    )


def build_nl_cases(events: tuple[MemoryEvent, ...]) -> tuple[NLQueryCase, ...]:
    """Resolve oracle query cases into value-level natural-language cases."""
    ingests = _ingest_by_belief(events)

    def value_of(belief_id: str) -> str | None:
        event = ingests.get(belief_id)
        return event.value if event else None

    def values(ids: frozenset[str]) -> frozenset[str]:
        return frozenset(
            value for value in (value_of(belief_id) for belief_id in ids) if value
        )

    cases: list[NLQueryCase] = []
    for case in cases_from_oracle(events):
        cases.append(
            NLQueryCase(
                case_id=case.case_id,
                query_text=render_query(case),
                subject=case.subject,
                attribute=case.attribute,
                valid_at=case.valid_at,
                transaction_at=case.transaction_at,
                expected_values=values(case.expected_ids),
                stale_values=values(case.stale_ids) - values(case.expected_ids),
                category=case.category,
            )
        )
    return tuple(cases)


_FALLBACK = re.compile(r"^(?:Person|[a-z]+(?:-[a-z]+)*)-\d+$")


def fallback_tokens(events: tuple[MemoryEvent, ...]) -> dict[str, int]:
    """How many distinct names and values are synthetic fallback tokens.

    Recorded with every run, so a confound like the one that motivated the
    large pools is visible in the artifact instead of being found by accident.
    """
    names = {e.subject for e in events if e.subject}
    values = {str(e.value) for e in events if e.value}
    return {
        "names": sum(bool(_FALLBACK.match(n)) for n in names),
        "names_total": len(names),
        "values": sum(bool(_FALLBACK.match(v)) for v in values),
        "values_total": len(values),
    }
