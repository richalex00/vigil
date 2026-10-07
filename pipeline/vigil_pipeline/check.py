"""Deterministic checks (no AI). Every field ends with exactly one status (spec §5.1, §7)."""
import math
from dataclasses import dataclass

from .contract import FieldResult
from .estimates import CARBON_ESTIMATE
from .ingest import Page
from .quotes import find_quote, norm
from .schema import FIELDS, Field
from .units import normalise_unit, numbers_in, parse_number


@dataclass
class RawField:
    id: str
    found: bool
    value: str
    unit: str
    quote: str
    page: int | None


def _base(field: Field, **kw) -> FieldResult:
    return FieldResult(id=field.id, label=field.label, cluster=field.cluster, kind=field.kind,
                       unit=field.unit, **kw)


def check_field(field: Field, raw: RawField | None, pages: list[Page]) -> FieldResult:
    if raw is None or not raw.found:
        if field.kind == "estimate":
            return _base(field, status="estimate", value=CARBON_ESTIMATE["value"],
                         estimate_note=CARBON_ESTIMATE["note"], reason="not in document; industry average")
        if field.kind == "supplier":
            return _base(field, status="supplier", value=None, reason="not in document; held by supplier")
        return _base(field, status="review", value=None, reason="not found in document")

    loc = find_quote(raw.quote, pages, raw.page)
    page, line, line_end = loc if loc else (raw.page, None, None)
    reasons: list[str] = []
    if loc is None:
        reasons.append("quote not found in document")

    value: float | str | None
    if field.vtype == "text":
        value = raw.value.strip()
        if loc is not None and norm(value) not in norm(raw.quote):
            reasons.append("value not in quote")
    else:
        number = parse_number(raw.value)
        converted = normalise_unit(raw.unit)
        if number is None:
            value = None
            reasons.append("value is not a number")
        elif converted is None or converted[0] != field.unit:
            value = None
            reasons.append(f"unit '{raw.unit}' not convertible to {field.unit}")
        else:
            value = round(number * converted[1], 9)
            if loc is not None and not any(math.isclose(number, n, rel_tol=1e-6) for n in numbers_in(raw.quote)):
                reasons.append("value not in quote")
            if not (field.min <= value <= field.max):
                reasons.append("value outside plausible range")

    return _base(field, status="review" if reasons else "verified-source", value=value,
                 raw_value=raw.value, raw_unit=raw.unit or None, quote=raw.quote, page=page,
                 line=line, line_end=line_end, reason=reasons[0] if reasons else None)


def _derive_energy(field: Field, by_id: dict[str, FieldResult]) -> FieldResult:
    cap, volt = by_id["rated_capacity"], by_id["nominal_voltage"]
    value = None
    if isinstance(cap.value, float) and isinstance(volt.value, float):
        value = round(cap.value * volt.value, 6)
    if cap.status == "verified-source" and volt.status == "verified-source":
        return _base(field, status="derived", value=value, reason=None)
    return _base(field, status="review", value=value, reason="depends on unverified field")


def check_all(raw: dict[str, RawField], pages: list[Page]) -> list[FieldResult]:
    by_id: dict[str, FieldResult] = {}
    for field in FIELDS:
        if field.kind != "derived":
            by_id[field.id] = check_field(field, raw.get(field.id), pages)
    for field in FIELDS:
        if field.kind == "derived":
            by_id[field.id] = _derive_energy(field, by_id)
    return [by_id[f.id] for f in FIELDS]
