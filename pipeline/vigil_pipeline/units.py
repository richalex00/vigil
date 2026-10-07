"""Unit normalisation and number parsing for datasheet values."""
import re
import unicodedata

_UNITS: dict[str, tuple[str, float]] = {
    "ah": ("Ah", 1.0), "mah": ("Ah", 0.001),
    "v": ("V", 1.0), "mv": ("V", 0.001),
    "a": ("A", 1.0), "ma": ("A", 0.001),
    "wh": ("Wh", 1.0), "kwh": ("Wh", 1000.0),
    "mω": ("mΩ", 1.0), "mohm": ("mΩ", 1.0), "milliohm": ("mΩ", 1.0),
    "ω": ("mΩ", 1000.0), "ohm": ("mΩ", 1000.0),
    "g": ("g", 1.0), "kg": ("g", 1000.0),
    "%": ("%", 1.0),
    "°c": ("°C", 1.0), "c": ("°C", 1.0), "degc": ("°C", 1.0), "deg.c": ("°C", 1.0),
    "oc": ("°C", 1.0),  # ASCII "oC", as some datasheets (e.g. Molicel) write degrees
    "cycles": ("cycles", 1.0), "cycle": ("cycles", 1.0), "cyc": ("cycles", 1.0),
}

# Units offered in the demo's "fix" input, in display order (canonical first).
_DISPLAY = {"ah": "Ah", "mah": "mAh", "v": "V", "mv": "mV", "a": "A", "ma": "mA", "wh": "Wh",
            "kwh": "kWh", "mω": "mΩ", "ω": "Ω", "g": "g", "kg": "kg", "%": "%", "°c": "°C",
            "cycles": "cycles"}

# A minus sign only counts when it isn't joining two numbers ("2.5-4.2" is a range).
_NUM_RE = re.compile(r"(?:(?<![\w.])-)?\d+(?:[ ,]\d{3})*(?:[.,]\d+)?")
_PARTS_RE = re.compile(r"(-?\d+(?:[ ,]\d{3})*)([.,]\d+)?")


def normalise_unit(raw: str) -> tuple[str, float] | None:
    key = unicodedata.normalize("NFKC", raw or "").casefold()
    key = re.sub(r"\s+", "", key).replace("º", "°")
    return _UNITS.get(key)


def allowed_units(canonical: str) -> list[str]:
    return [label for key, label in _DISPLAY.items() if _UNITS[key][0] == canonical]


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-").replace("–", "-")


def _to_float(token: str) -> float:
    m = _PARTS_RE.fullmatch(token)
    integer = re.sub(r"[ ,]", "", m.group(1))
    frac = (m.group(2) or "").replace(",", ".")
    return float(integer + frac)


def numbers_in(text: str) -> list[float]:
    return [_to_float(t) for t in _NUM_RE.findall(_clean(text))]


def parse_number(text: str) -> float | None:
    nums = numbers_in(text)
    return nums[0] if nums else None
