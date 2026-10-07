"""The JSON contract between the pipeline and the demo app. Plan 2 mirrors these shapes in TypeScript."""
from dataclasses import asdict, dataclass
from typing import Literal

Status = Literal["verified-source", "review", "estimate", "supplier", "derived"]
STATUSES = ("verified-source", "review", "estimate", "supplier", "derived")


@dataclass
class FieldResult:
    id: str
    label: str
    cluster: str
    kind: str
    status: Status
    value: float | str | None
    unit: str | None
    raw_value: str | None = None
    raw_unit: str | None = None
    quote: str | None = None
    page: int | None = None
    line: int | None = None
    line_end: int | None = None
    reason: str | None = None
    estimate_note: str | None = None


@dataclass
class RunInfo:
    method: Literal["checked", "baseline"]
    model: str
    served_model: str
    elapsed_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class DatasheetResult:
    id: str
    title: str
    source_file: str
    pages: list[dict]
    fields: list[FieldResult]
    run: RunInfo
    contract_version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)
