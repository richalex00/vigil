"""Industry-average defaults for estimable fields (spec §5.1 'estimate').

Source: IVL Swedish Environmental Research Institute, report C444 (Emilsson & Dahllöf, 2019),
"Lithium-Ion Vehicle Battery Production" - 61-106 kg CO2e per kWh of battery capacity, production
only (cradle-to-gate). The regulation's passport carbon footprint is a life-cycle value with a
different functional unit, so this is shown as a labelled stand-in, never as a declared value."""
CARBON_ESTIMATE = {
    "value": 83.5,
    "unit": "kg CO2e/kWh",
    "note": ("Estimate, not a declared value: midpoint of the 61-106 kg CO2e per kWh of battery "
             "capacity range for production (cradle-to-gate) in IVL report C444 (2019). The "
             "passport's own figure is a life-cycle value."),
}
