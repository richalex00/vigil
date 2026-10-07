"""A passport-shaped slice of the EU battery passport (Reg. 2023/1542 Annex XIII), 25 fields.

Not every field is passport-mandated (e.g. max discharge current is a datasheet field kept for
context; UN 38.3 / EU declaration sit in conformity documentation)."""
from dataclasses import dataclass
from typing import Literal

Kind = Literal["source", "derived", "estimate", "supplier"]
VType = Literal["number", "text"]
Match = Literal["exact", "tokens"]

CLUSTERS = ("general", "performance", "materials", "carbon", "circularity", "compliance")
CLUSTER_LABELS = {
    "general": "General information",
    "performance": "Performance & durability",
    "materials": "Materials & composition",
    "carbon": "Carbon footprint",
    "circularity": "Circularity & safety",
    "compliance": "Compliance",
}


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    cluster: str
    kind: Kind
    vtype: VType
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    hint: str = ""
    match: Match = "exact"  # text fields only: exact (identifiers) or tokens (free text)


FIELDS: tuple[Field, ...] = (
    Field("manufacturer", "Manufacturer", "general", "source", "text"),
    Field("model_identifier", "Model identifier", "general", "source", "text"),
    Field("battery_category", "Battery category", "general", "source", "text",
          hint="portable, LMT, EV, industrial or SLI - only if the document states it"),
    Field("chemistry", "Chemistry", "general", "source", "text",
          hint="cathode chemistry, e.g. NMC, LFP, NCA"),
    Field("weight", "Weight", "general", "source", "number", "g", 1, 1_500_000),
    Field("manufacturing_date", "Manufacturing date", "general", "supplier", "text"),
    Field("rated_capacity", "Rated capacity", "performance", "source", "number", "Ah", 0.01, 2000,
          hint="nominal or rated capacity, not minimum capacity"),
    Field("nominal_voltage", "Nominal voltage", "performance", "source", "number", "V", 1, 1000),
    Field("min_voltage", "Minimum voltage", "performance", "source", "number", "V", 0.5, 1000,
          hint="discharge cut-off voltage"),
    Field("max_voltage", "Maximum voltage", "performance", "source", "number", "V", 1, 1000,
          hint="charge (end) voltage"),
    Field("max_discharge_current", "Max continuous discharge current", "performance", "source",
          "number", "A", 0.01, 5000),
    Field("internal_resistance", "Internal resistance", "performance", "source", "number",
          "mΩ", 0.01, 100_000, hint="AC or DC impedance; the quote must show which"),
    Field("expected_lifetime_cycles", "Expected lifetime", "performance", "source", "number",
          "cycles", 10, 100_000),
    Field("capacity_threshold_pct", "Capacity threshold for exhaustion", "performance", "source",
          "number", "%", 50, 100, hint="end-of-life capacity percentage the cycle life is rated to"),
    Field("operating_temp_min", "Min operating temperature", "performance", "source", "number",
          "°C", -60, 30, hint="lowest discharge temperature"),
    Field("operating_temp_max", "Max operating temperature", "performance", "source", "number",
          "°C", 20, 120, hint="highest discharge temperature"),
    Field("rated_energy", "Rated energy", "performance", "derived", "number", "Wh", 0.01, 2_000_000),
    Field("hazardous_substances", "Hazardous substances", "materials", "source", "text", match="tokens"),
    Field("critical_raw_materials", "Critical raw materials content", "materials", "supplier", "text",
          match="tokens"),
    Field("recycled_content_share", "Recycled content share", "materials", "supplier", "text",
          match="tokens"),
    Field("carbon_footprint", "Carbon footprint (production estimate)", "carbon", "estimate", "number",
          "kg CO2e/kWh", 10, 500),
    Field("dismantling_info", "Dismantling & removal information", "circularity", "source", "text",
          match="tokens"),
    Field("extinguishing_agent", "Extinguishing agent", "circularity", "source", "text", match="tokens"),
    Field("un38_3_test", "UN 38.3 transport test", "compliance", "source", "text", match="tokens"),
    Field("eu_declaration_ref", "EU declaration of conformity", "compliance", "source", "text",
          match="tokens"),
)

FIELD_BY_ID: dict[str, Field] = {f.id: f for f in FIELDS}
EXTRACTABLE: tuple[Field, ...] = tuple(f for f in FIELDS if f.kind != "derived")
SOURCE_FIELDS: tuple[Field, ...] = tuple(f for f in FIELDS if f.kind == "source")
