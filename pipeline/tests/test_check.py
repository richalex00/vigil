from vigil_pipeline.check import RawField, check_all, check_field
from vigil_pipeline.ingest import Page
from vigil_pipeline.schema import FIELD_BY_ID, FIELDS

PAGES = [Page(1, [
    "Model INR18650 MJ1", "Nominal Capacity 3500 mAh", "Nominal Voltage 3.635 V",
    "Charge voltage 4.2 V", "Cathode: NMC", "Weight 49.0 g max",
])]


def raw(id, value, unit="", quote="", page=1, found=True):
    return RawField(id=id, found=found, value=value, unit=unit, quote=quote, page=page)


def test_verified_number_is_converted():
    r = check_field(FIELD_BY_ID["rated_capacity"],
                    raw("rated_capacity", "3500", "mAh", "Nominal Capacity 3500 mAh"), PAGES)
    assert (r.status, r.value, r.unit, r.page, r.line, r.line_end, r.reason) == \
        ("verified-source", 3.5, "Ah", 1, 2, 2, None)


def test_invented_quote_goes_to_review_but_keeps_value():
    r = check_field(FIELD_BY_ID["rated_capacity"],
                    raw("rated_capacity", "3600", "mAh", "Nominal Capacity 3600 mAh"), PAGES)
    assert r.status == "review" and r.reason == "quote not found in document" and r.value == 3.6


def test_value_not_in_quote():
    r = check_field(FIELD_BY_ID["nominal_voltage"],
                    raw("nominal_voltage", "3.7", "V", "Nominal Voltage 3.635 V"), PAGES)
    assert r.status == "review" and r.reason == "value not in quote"


def test_unconvertible_unit():
    r = check_field(FIELD_BY_ID["weight"], raw("weight", "49.0", "oz", "Weight 49.0 g max"), PAGES)
    assert r.status == "review" and r.reason.startswith("unit 'oz'")


def test_out_of_range():
    r = check_field(FIELD_BY_ID["max_voltage"], raw("max_voltage", "4.2", "mV", "Charge voltage 4.2 V"), PAGES)
    assert r.status == "review" and r.reason == "value outside plausible range"


def test_text_field_verified_and_value_in_quote():
    ok = check_field(FIELD_BY_ID["chemistry"], raw("chemistry", "NMC", quote="Cathode: NMC"), PAGES)
    bad = check_field(FIELD_BY_ID["chemistry"], raw("chemistry", "LFP", quote="Cathode: NMC"), PAGES)
    assert ok.status == "verified-source" and ok.value == "NMC"
    assert bad.status == "review" and bad.reason == "value not in quote"


def test_not_found_statuses_by_kind():
    assert check_field(FIELD_BY_ID["manufacturer"], None, PAGES).reason == "not found in document"
    assert check_field(FIELD_BY_ID["manufacturer"], None, PAGES).status == "review"
    assert check_field(FIELD_BY_ID["recycled_content_share"], None, PAGES).status == "supplier"
    est = check_field(FIELD_BY_ID["carbon_footprint"], raw("carbon_footprint", "", found=False), PAGES)
    assert est.status == "estimate" and est.value == 83.5
    assert "IVL" in est.estimate_note and "cradle-to-gate" in est.estimate_note


def test_check_all_covers_every_field_and_derives_energy():
    results = check_all({
        "rated_capacity": raw("rated_capacity", "3500", "mAh", "Nominal Capacity 3500 mAh"),
        "nominal_voltage": raw("nominal_voltage", "3.635", "V", "Nominal Voltage 3.635 V"),
        "bogus_id": raw("bogus_id", "x"),
    }, PAGES)
    assert [r.id for r in results] == [f.id for f in FIELDS]
    energy = next(r for r in results if r.id == "rated_energy")
    assert energy.status == "derived" and abs(energy.value - 12.7225) < 1e-6


def test_derived_depends_on_unverified():
    results = check_all({
        "rated_capacity": raw("rated_capacity", "3600", "mAh", "Nominal Capacity 3600 mAh"),
        "nominal_voltage": raw("nominal_voltage", "3.635", "V", "Nominal Voltage 3.635 V"),
    }, PAGES)
    energy = next(r for r in results if r.id == "rated_energy")
    assert energy.status == "review" and energy.reason == "depends on unverified field"
