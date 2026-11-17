"""Generate the fictional Apex Industrial sample documents (PDFs need reportlab; dev dependency).

All content is invented for this demonstration. Run: python sample-data/customer-a/generate_samples.py
"""
import csv
import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent

MANUAL_PAGES = [
    ("Apex CP-200 Centrifugal Pump - Operation and Maintenance Manual (fictional)", [
        "Section 1: Overview. The CP-200 is a single-stage centrifugal process pump used for cooling water "
        "circulation at Apex Industrial Manufacturing plants. Rated flow is 120 m3/h at 32 m head.",
        "Section 2: Routine Inspection. Inspect the drive-end and non-drive-end bearing housings weekly. "
        "Record vibration velocity at both bearings in mm/s RMS and compare against the previous reading.",
    ]),
    ("Section 3: Troubleshooting Abnormal Vibration", [
        "If vibration velocity exceeds 7.1 mm/s RMS at the drive-end bearing, stop the pump when safe and "
        "inspect the bearing housing for wear and lubricant contamination.",
        "Check coupling alignment; angular and parallel offset must be below 0.05 mm.",
        "Replace the drive-end bearing set (PN-4417) if bearing temperature exceeds 85 C or if abnormal "
        "vibration persists after realignment.",
        "Cavitation produces a gravel-like noise and fluctuating vibration; verify suction pressure and clear "
        "the inlet strainer.",
        "An unbalanced impeller causes vibration at one times running speed; inspect and rebalance the impeller.",
    ]),
    ("Section 4: Seals, Overheating and Safety", [
        "A leaking mechanical seal must be replaced using seal kit PN-5102. Never run the pump dry.",
        "If the motor overheats, check cooling fin cleanliness and ventilation before restarting.",
        "Lock out and tag out the pump before any maintenance work.",
    ]),
]

INSPECTION_PAGES = [
    ("Q3 2026 Inspection Report - Cooling Water Pumps (fictional)", [
        "P-101: drive-end vibration measured 5.9 mm/s RMS, trending up from 3.4 mm/s in Q2. "
        "Recommend a coupling alignment check at the next planned outage.",
        "P-102: all readings within limits. Lubricant replaced.",
        "P-103: mechanical seal shows minor weeping; monitor weekly.",
    ]),
]


def write_pdf(path: Path, pages):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    for title, paragraphs in pages:
        y = 800
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, title[:90])
        y -= 30
        c.setFont("Helvetica", 10.5)
        for para in paragraphs:
            for line in textwrap.wrap(para, 92):
                c.drawString(50, y, line)
                y -= 15
            y -= 8
        c.showPage()
    c.save()


def write_csv(path: Path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    write_pdf(OUT / "apex_cp200_pump_manual.pdf", MANUAL_PAGES)
    write_pdf(OUT / "apex_inspection_report_2026q3.pdf", INSPECTION_PAGES)
    write_csv(OUT / "equipment_register.csv", ["equipment_id", "name", "model", "location", "commissioned"], [
        ["P-101", "Cooling water pump 1", "CP-200", "Plant 1 Bay 3", "2019-04-02"],
        ["P-102", "Cooling water pump 2", "CP-200", "Plant 1 Bay 3", "2019-04-02"],
        ["P-103", "Process water pump", "CP-200", "Plant 1 Bay 4", "2021-09-15"],
        ["M-201", "Compressor motor", "EM-55", "Plant 2 Bay 1", "2020-01-20"],
    ])
    write_csv(OUT / "incident_history.csv",
              ["incident_id", "date", "equipment_id", "category", "description", "root_cause", "resolution"], [
        ["INC-2024-0412", "2024-03-12", "P-101", "mechanical_vibration",
         "Drive-end bearing vibration reached 8.2 mm/s during weekly round",
         "Worn drive-end bearing", "Replaced bearing set PN-4417 and realigned coupling"],
        ["INC-2025-0107", "2025-01-20", "P-101", "mechanical_vibration",
         "Intermittent vibration with gravel-like noise",
         "Partially blocked suction strainer causing cavitation",
         "Cleaned inlet strainer; vibration returned to 2.1 mm/s"],
        ["INC-2025-0633", "2025-06-02", "P-102", "mechanical_vibration",
         "High vibration 7.8 mm/s after maintenance", "Coupling misalignment of 0.12 mm",
         "Realigned coupling to 0.03 mm"],
        ["INC-2024-0899", "2024-08-30", "P-103", "leak", "Mechanical seal leaking",
         "Seal face wear", "Replaced seal kit PN-5102"],
        ["INC-2025-0301", "2025-03-11", "M-201", "overheating", "Motor winding temperature alarm",
         "Blocked cooling fins", "Cleaned cooling fins and verified airflow"],
    ])
    write_csv(OUT / "maintenance_log.csv", ["log_id", "date", "equipment_id", "work_done", "technician"], [
        ["ML-9001", "2026-08-14", "P-101", "Weekly bearing inspection; lubricant topped up", "R. Okafor"],
        ["ML-9002", "2026-08-21", "P-101", "Weekly bearing inspection; no findings", "R. Okafor"],
        ["ML-9003", "2026-09-02", "P-102", "Replaced lubricant", "L. Brandt"],
    ])


if __name__ == "__main__":
    main()
