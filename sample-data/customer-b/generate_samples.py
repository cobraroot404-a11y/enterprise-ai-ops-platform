"""Generate the fictional Meridian Fleet Logistics sample documents (PDFs need reportlab; dev dependency).

All content is invented for this demonstration. Run: python sample-data/customer-b/generate_samples.py
Column names deliberately differ from Customer A's files: Meridian's onboarding profile maps them.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "customer-a"))
from generate_samples import write_pdf  # noqa: E402  (reuse the PDF writer; nothing Apex-specific in it)

OUT = Path(__file__).parent

MANUAL_PAGES = [
    ("Meridian MX-300 Refrigerated Delivery Truck - Maintenance Manual (fictional)", [
        "Section 1: Overview. The MX-300 is a refrigerated medium-duty delivery truck used by Meridian Fleet "
        "Logistics for temperature-controlled city routes. It uses an air-brake system and a liquid-cooled diesel engine.",
        "Section 2: Pre-trip Inspection. Drivers record service brake line pressure in psi and coolant "
        "temperature in C at every pre-trip check and compare them with the previous reading.",
    ]),
    ("Section 3: Troubleshooting Low Brake Pressure", [
        "If service brake line pressure falls below 55 psi, remove the vehicle from its route and inspect the "
        "brake lines, fittings and air dryer for leaks. A vehicle below 40 psi must not be driven.",
        "Drain the air tanks and replace the air dryer cartridge (PN-7731) if moisture is found in the brake lines.",
        "Replace the rear brake chamber kit (PN-7790) if the diaphragm is cracked or if a hissing leak persists "
        "after tightening fittings.",
    ]),
    ("Section 4: Engine Cooling and Refrigeration Unit", [
        "If coolant temperature exceeds 105 C, stop safely and allow the engine to cool. Check coolant level and "
        "radiator fin cleanliness before restarting.",
        "Replace the thermostat (PN-8120) if coolant temperature exceeds 115 C after the system has been refilled.",
        "If the refrigeration unit cargo temperature rises above -15 C, check the condenser fan and notify "
        "dispatch because the cargo may be at risk.",
        "Lock out the vehicle and apply wheel chocks before any under-vehicle maintenance work.",
    ]),
]

INSPECTION_PAGES = [
    ("Q3 2026 Depot Inspection Report - MX-300 Fleet (fictional)", [
        "VH-2101: rear service brake line pressure measured 58 psi, trending down from 66 psi in Q2. "
        "Recommend an air dryer service at the next scheduled stop.",
        "VH-2102: all readings within limits. Coolant replaced.",
        "VH-2103: coolant seep at the lower radiator hose; monitor weekly.",
    ]),
]


def write_csv(path: Path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    write_pdf(OUT / "meridian_mx300_maintenance_manual.pdf", MANUAL_PAGES)
    write_pdf(OUT / "meridian_depot_inspection_2026q3.pdf", INSPECTION_PAGES)
    write_csv(OUT / "fleet_register.csv", ["unit_id", "description", "model", "depot", "in_service", "account_code"], [
        ["VH-2101", "Refrigerated delivery truck 1", "MX-300", "Harbor Depot", "2022-03-14", "ACC-501"],
        ["VH-2102", "Refrigerated delivery truck 2", "MX-300", "Harbor Depot", "2022-03-14", "ACC-501"],
        ["VH-2103", "Refrigerated delivery truck 3", "MX-300", "Northside Depot", "2023-06-01", "ACC-502"],
        ["VH-2104", "Regional tractor 1", "MX-450", "Northside Depot", "2021-11-09", "ACC-503"],
    ])
    write_csv(OUT / "service_history.csv",
              ["record_ref", "service_date", "unit_id", "issue_type", "issue_summary", "cause", "fix"], [
        ["SR-3001", "2025-02-18", "VH-2101", "brake_system",
         "Low brake line pressure of 49 psi reported at pre-trip",
         "Saturated air dryer cartridge", "Replaced air dryer cartridge PN-7731"],
        ["SR-3002", "2025-05-07", "VH-2102", "brake_system",
         "Hissing leak at rear brake chamber with pressure drop to 52 psi",
         "Cracked brake chamber diaphragm", "Replaced brake chamber kit PN-7790"],
        ["SR-3003", "2025-08-22", "VH-2104", "engine_cooling",
         "Coolant temperature reached 118 C on a hill climb",
         "Failed thermostat", "Replaced thermostat PN-8120"],
        ["SR-3004", "2025-10-03", "VH-2103", "refrigeration_unit",
         "Cargo temperature rose to -12 C during a delivery",
         "Condenser fan motor fault", "Replaced condenser fan motor"],
    ])
    write_csv(OUT / "telematics_alerts.csv", ["alert_ref", "raised_at", "unit_id", "alert_code", "alert_text"], [
        ["AL-5001", "2026-09-04T06:12:00", "VH-2101", "BRK-LOW", "Service brake line pressure low at 57 psi"],
        ["AL-5002", "2026-09-09T14:40:00", "VH-2104", "ENG-HOT", "Coolant temperature high at 108 C"],
        ["AL-5003", "2026-09-11T09:05:00", "VH-2103", "COOL-RAD", "Possible coolant seep detected from radiator hose"],
    ])


if __name__ == "__main__":
    main()
