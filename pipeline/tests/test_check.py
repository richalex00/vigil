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


WRAPPED = [Page(1, ["Initial Internal Resistance AC, 1 kHz, Delivery SOC,", "0.18 mΩ 0.05 mΩ",
                    "Nominal Voltage 3.2 V typ", "4.0 V max"])]


def test_value_on_line_after_wrapped_label_is_verified():
    r = check_field(FIELD_BY_ID["internal_resistance"],
                    raw("internal_resistance", "0.18", "mΩ",
                        "Initial Internal Resistance AC, 1 kHz, Delivery SOC,"), WRAPPED)
    assert r.status == "verified-source" and r.line == 1


def test_only_first_number_on_wrapped_line_counts_not_tolerance():
    # "0.18 mΩ 0.05 mΩ" is value cell then tolerance cell; both carry mΩ, so only position tells them apart.
    quote = "Initial Internal Resistance AC, 1 kHz, Delivery SOC,"
    ok = check_field(FIELD_BY_ID["internal_resistance"],
                     raw("internal_resistance", "0.18", "mΩ", quote), WRAPPED)
    tol = check_field(FIELD_BY_ID["internal_resistance"],
                      raw("internal_resistance", "0.05", "mΩ", quote), WRAPPED)
    assert ok.status == "verified-source"
    assert tol.status == "review" and tol.reason == "value not in quote"


def test_next_line_not_used_when_quote_stops_mid_line():
    # The quote ends before the line does, so the next line is not its value cell.
    r = check_field(FIELD_BY_ID["nominal_voltage"],
                    raw("nominal_voltage", "4.0", "V", "Nominal Voltage 3.2 V"), WRAPPED)
    assert r.status == "review" and r.reason == "value not in quote"


HEADER = [Page(1, ["USER GUIDE FOR THE ACME CELL PACK, SUITABLE FOR", "MODEL X SERIES WITH 48 V",
                   "9.2 While the product contains no mercury or other listed substance,",
                   "such as lead or cadmium, it must be recycled under local rules"])]


def test_free_text_value_may_continue_on_next_line():
    r = check_field(FIELD_BY_ID["hazardous_substances"],
                    raw("hazardous_substances",
                        "contains no mercury or other listed substance, such as lead or cadmium", "",
                        "While the product contains no mercury or other listed substance,"), HEADER)
    assert r.status == "verified-source"


def test_identifier_must_lie_wholly_inside_quote():
    r = check_field(FIELD_BY_ID["model_identifier"],
                    raw("model_identifier", "ACME CELL PACK, SUITABLE FOR MODEL X SERIES WITH 48 V",
                        "", "USER GUIDE FOR THE ACME CELL PACK, SUITABLE FOR"), HEADER)
    assert r.status == "review" and r.reason == "value not in quote"
