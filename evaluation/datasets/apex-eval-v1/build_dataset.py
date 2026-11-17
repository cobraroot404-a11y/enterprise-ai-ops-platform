"""Build the synthetic Apex evaluation dataset (v1). All content is fictional and written for this project.

Run: python evaluation/datasets/apex-eval-v1/build_dataset.py
Outputs (committed): documents/*.pdf|csv, queries.jsonl, reports.jsonl, dataset_manifest.json

Relevance is defined at the level of a "unit": (filename, page) for PDFs or (filename, record_id) for CSVs.
Queries are split into `dev` (used only to calibrate the evidence threshold) and `test` (held out).
"""
import csv
import hashlib
import json
import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
DOCS = OUT / "documents"

MANUALS = {
    "eval_cp200_pump_manual.pdf": ("CP-200 Centrifugal Pump Manual (fictional)", [
        ("Bearing lubrication", "Lubricate the drive-end and non-drive-end bearings with NLGI 2 lithium complex grease. "
         "Re-grease every 2,000 operating hours using 15 g per bearing. Over-greasing raises bearing temperature, so never "
         "exceed the stated quantity. Do not mix different grease types."),
        ("Mechanical seal", "The mechanical seal uses flush plan 11. Replace the seal if leakage exceeds 10 drops per "
         "minute. Use seal kit PN-5102. Running the pump dry destroys the seal faces within 30 seconds, so confirm the "
         "casing is primed before every start."),
        ("Cavitation", "Cavitation produces a gravel-like rattling noise at the inlet and fluctuating vibration. Keep an "
         "NPSH margin of at least 0.5 m. Check the inlet strainer differential pressure, keep the suction valve fully open "
         "and limit suction line velocity to 2 m/s."),
        ("Shaft alignment", "Align the pump and motor shafts with a laser tool. Parallel offset and angular misalignment "
         "must both stay below 0.05 mm (angular per 100 mm). Allow a thermal growth offset of 0.1 mm for hot service and "
         "check for soft foot before final tightening."),
        ("Start-up and shutdown", "Prime the casing, confirm rotation direction and start with the discharge valve about "
         "10 percent open. Open the valve gradually once pressure is stable. To stop, close the discharge valve slowly, "
         "stop the motor and apply lock-out and tag-out before maintenance."),
        ("Vibration limits", "Measure vibration velocity at the drive-end bearing housing in mm/s RMS. The alarm level is "
         "4.5 mm/s and the trip level is 7.1 mm/s. Trend readings weekly; a steady rise usually indicates bearing wear or "
         "misalignment."),
    ]),
    "eval_em55_motor_manual.pdf": ("EM-55 Electric Motor Manual (fictional)", [
        ("Winding temperature", "The stator uses class F insulation rated to 155 C. The alarm is set at 130 C using the "
         "Pt100 sensor in the stator. The most common cause of a high winding temperature is blocked cooling fins; clean "
         "the fins every quarter."),
        ("Insulation resistance", "Measure insulation resistance with a 500 V megohmmeter. The minimum acceptable value is "
         "100 MOhm. Below 10 MOhm the motor must not be energized; dry the windings with low-voltage heating and retest."),
        ("Bearing noise", "The motor uses 6312 C3 bearings with a 3,000 hour grease interval. A high-pitched squeal means "
         "lubricant starvation; a low rumble means bearing wear. Replace both bearings together when worn."),
        ("Overload trips", "Set the thermal overload to 105 percent of the full load current of 98 A. Repeated trips with "
         "a correct setting point to phase imbalance above 2 percent, loose terminals or excessive voltage drop. Check all "
         "three phases before resetting."),
        ("Cooling and derating", "Keep the fan cover clear of obstructions. The ambient temperature limit is 40 C; derate "
         "output by 2 percent for each 5 C above that limit."),
    ]),
    "eval_cc300_compressor_manual.pdf": ("CC-300 Screw Compressor Manual (fictional)", [
        ("Oil carryover", "Oil in the discharge air indicates a failed separator element or an overfilled sump. Replace "
         "the separator element PN-8801 every 8,000 hours or when its differential pressure reaches 1.0 bar."),
        ("Discharge temperature", "The discharge temperature alarm is 105 C and the compressor trips at 115 C. Typical "
         "causes are low oil level, a clogged oil cooler or high ambient temperature. The thermostatic valve opens at 71 C."),
        ("Pressure drop and capacity", "Change the intake filter PN-8810 when the vacuum indicator shows red. Falling "
         "delivery pressure can also come from leaks in the air receiver or a sticking unloader valve."),
        ("Valve plate failure", "A failed valve plate causes reduced capacity and a high interstage temperature. Replace "
         "the valve plates PN-8822 and torque the cover bolts to 35 Nm."),
        ("Mounting and vibration", "Inspect the anti-vibration pads every six months and torque foundation bolts to 120 Nm. "
         "The vibration limit for this compressor is 6.0 mm/s RMS."),
    ]),
    "eval_cv400_conveyor_manual.pdf": ("CV-400 Belt Conveyor Manual (fictional)", [
        ("Belt tracking", "A belt that drifts toward one side is normally running toward its tight side. Adjust the "
         "training idlers by 1 to 2 degrees, check tail pulley alignment and inspect the skirting for wear."),
        ("Gearbox noise", "Use ISO VG 220 gear oil and change it every 5,000 hours. A metallic whine indicates low oil "
         "or gear wear. Inspect the drain plug magnet for metal particles."),
        ("Idler rollers", "A seized idler roller scores and damages the belt. Replace an idler when its surface is 20 C "
         "hotter than its neighbors or when it is noisy. Use idler PN-9105."),
        ("Overload trips", "Overload trips are caused by a jammed chute, excessive belt tension or a failing gearbox. "
         "The motor current limit is 85 A. Clear the chute and check take-up tension before restarting."),
    ]),
    "eval_gb500_gearbox_manual.pdf": ("GB-500 Industrial Gearbox Manual (fictional)", [
        ("Oil leaks", "Oil at the output shaft usually means a worn shaft seal PN-9301. A blocked breather pressurizes the "
         "casing and pushes oil past the seals; clean the breather first. Check the casing split line sealant."),
        ("Overheating", "The sump temperature limit is 90 C. Check the oil level and viscosity, and make sure the cooling "
         "fan is turning and unobstructed."),
        ("Gear noise and backlash", "Acceptable backlash is 0.15 to 0.25 mm. Check the tooth contact pattern; pitting on "
         "the tooth flanks means the gear set is reaching end of life."),
        ("Coupling alignment", "Align the input coupling to within 0.08 mm. Misalignment overloads the bearings and "
         "shortens gearbox life."),
    ]),
    "eval_ht600_heat_exchanger_manual.pdf": ("HT-600 Shell-and-Tube Heat Exchanger Manual (fictional)", [
        ("Fouling", "Fouling shows as a rising approach temperature. Clean the exchanger when the approach temperature is "
         "5 C above baseline. Chemical cleaning uses 5 percent citric acid."),
        ("Tube leaks", "Pressure test at 1.3 times the design pressure of 16 bar. A sudden rise in cooling circuit "
         "conductivity indicates a tube leak. Up to 10 percent of tubes may be plugged before retubing."),
        ("Pressure drop", "The differential pressure limit is 0.8 bar. A higher reading points to a blocked strainer or "
         "fouled tubes; verify the flow rate before cleaning."),
        ("Cleaning procedure", "Isolate and drain the exchanger, circulate the cleaning solution for 4 hours, then rinse "
         "and neutralize until the pH is between 6.5 and 8.0."),
    ]),
}

INSPECTIONS = {
    "eval_inspection_2026q2.pdf": ("Q2 2026 Inspection Summary (fictional)", [
        ("Rotating equipment", "P-103: drive-end vibration 6.9 mm/s RMS, above the alarm level; soft foot suspected. "
         "P-104: new seal weeping after commissioning. M-202: winding temperature 128 C, cooling fins dusty."),
        ("Utilities", "CC-301: discharge temperature 101 C and rising, oil cooler fins dirty. H-601: approach "
         "temperature 4 C above baseline. CV-402: gearbox oil level low at the sight glass."),
    ]),
    "eval_inspection_2026q3.pdf": ("Q3 2026 Inspection Summary (fictional)", [
        ("Rotating equipment", "P-103: vibration back to 3.1 mm/s after the foot was shimmed. M-202: winding temperature "
         "118 C after cleaning. G-502: backlash measured at 0.38 mm, outside the 0.15 to 0.25 mm limit."),
        ("Utilities", "CC-301: discharge temperature 96 C. H-601: approach temperature 7 C above baseline, cleaning "
         "scheduled. CV-401: belt edge wear on the drive side."),
    ]),
}

REGISTER = [
    ("P-101", "Cooling water pump 1", "CP-200", "Plant 1 Bay 3"), ("P-102", "Cooling water pump 2", "CP-200", "Plant 1 Bay 3"),
    ("P-103", "Process water pump", "CP-200", "Plant 1 Bay 4"), ("P-104", "Boiler feed pump", "CP-200", "Plant 1 Bay 5"),
    ("M-201", "Compressor motor A", "EM-55", "Plant 2 Bay 1"), ("M-202", "Compressor motor B", "EM-55", "Plant 2 Bay 1"),
    ("M-203", "Fan motor", "EM-55", "Plant 2 Bay 2"), ("CC-301", "Air compressor 1", "CC-300", "Plant 2 Bay 1"),
    ("CC-302", "Air compressor 2", "CC-300", "Plant 2 Bay 1"), ("CV-401", "Feed conveyor", "CV-400", "Plant 3 Line 1"),
    ("CV-402", "Discharge conveyor", "CV-400", "Plant 3 Line 1"), ("G-501", "Mixer gearbox", "GB-500", "Plant 3 Line 2"),
    ("G-502", "Crusher gearbox", "GB-500", "Plant 3 Line 2"), ("H-601", "Process cooler", "HT-600", "Plant 1 Bay 6"),
]

TARGETED_INCIDENTS = [
    ("INC-2025-1001", "CV-401", "noise", "Seized idler roller scoring the belt", "Idler bearing seized", "Replaced idler PN-9105 and the damaged belt section"),
    ("INC-2025-1002", "CC-301", "performance_degradation", "Oil carryover into the air line after 9,500 operating hours", "Separator element beyond service life", "Replaced separator element PN-8801"),
    ("INC-2025-1003", "M-202", "overheating", "Winding temperature alarm at 138 C", "Cooling fins blocked with dust", "Cleaned the cooling fins"),
    ("INC-2025-1004", "P-104", "leak", "Mechanical seal leaking 20 drops per minute after commissioning", "Pump run dry during start-up", "Replaced seal with kit PN-5102 and added a priming check"),
    ("INC-2025-1005", "G-501", "leak", "Oil leak at the output shaft", "Blocked breather pressurized the casing", "Replaced breather and shaft seal PN-9301"),
    ("INC-2025-1006", "H-601", "performance_degradation", "Approach temperature rose 8 C above baseline", "Tube fouling", "Chemical cleaning with citric acid"),
    ("INC-2025-1007", "CC-302", "overheating", "Discharge temperature trip at 116 C", "Oil cooler clogged with dust", "Cleaned the oil cooler and topped up oil"),
    ("INC-2025-1008", "M-203", "electrical_fault", "Insulation resistance only 4 MOhm after a flood", "Moisture in the windings", "Dried windings with low-voltage heating; retest gave 250 MOhm"),
    ("INC-2025-1009", "CV-402", "noise", "Metallic whine from the gearbox", "Low gear oil level", "Refilled ISO VG 220 oil and replaced the seal"),
    ("INC-2025-1010", "P-103", "mechanical_vibration", "Vibration of 6.9 mm/s at the drive end", "Soft foot at the motor mounting", "Shimmed the foot and realigned"),
    ("INC-2025-1011", "P-102", "noise", "Gravel-like noise and high strainer differential pressure", "Blocked inlet strainer causing cavitation", "Cleaned the strainer"),
    ("INC-2025-1012", "H-601", "leak", "Cooling water conductivity rose sharply", "Tube leak", "Plugged three tubes"),
    ("INC-2025-1013", "CC-301", "performance_degradation", "Reduced capacity and high interstage temperature", "Failed valve plate", "Replaced valve plates PN-8822"),
    ("INC-2025-1014", "CV-401", "other", "Belt drifting toward the tight side", "Training idler out of position", "Adjusted the training idler by 1.5 degrees"),
    ("INC-2025-1015", "G-502", "noise", "Gear noise with 0.4 mm backlash", "Pitting on gear teeth", "Replaced the gear set"),
    ("INC-2025-1016", "M-201", "electrical_fault", "Repeated thermal overload trips", "Phase imbalance of 3.5 percent from a loose terminal", "Tightened the terminal"),
]
FILLER = [
    ("P-101", "mechanical_vibration", "Routine vibration reading above trend", "Bearing wear", "Scheduled bearing replacement"),
    ("P-102", "leak", "Minor seal weeping", "Seal face wear", "Monitored and replaced at next outage"),
    ("M-201", "overheating", "Warm bearing housing", "Excess grease", "Removed excess grease"),
    ("CC-302", "noise", "Rattling from the enclosure", "Loose panel", "Tightened panel fasteners"),
    ("CV-402", "other", "Skirting rubber worn", "Normal wear", "Replaced skirting rubber"),
    ("G-501", "overheating", "Sump temperature high on a hot day", "High ambient", "Cleaned cooling fan guard"),
    ("H-601", "performance_degradation", "Slight pressure drop increase", "Strainer partly blocked", "Cleaned strainer"),
    ("P-104", "noise", "Humming at the coupling guard", "Guard resonance", "Added damping strip"),
]

# Answerable queries: (id, split, type, query, [(file, page|record_id)], key facts that a correct answer should contain)
Q = [
    ("D01", "dev", "keyword", "How often should the pump bearings be re-greased and with how much?", [("eval_cp200_pump_manual.pdf", 1)], ["2,000", "15"]),
    ("D02", "dev", "paraphrase", "What does a gravelly rattling sound from the pump inlet suggest?", [("eval_cp200_pump_manual.pdf", 3)], ["cavitation"]),
    ("D03", "dev", "paraphrase", "What's the minimum insulation reading before a motor can be safely powered up?", [("eval_em55_motor_manual.pdf", 2)], ["100"]),
    ("D04", "dev", "paraphrase", "The compressor is blowing oil into the air line, what is wrong?", [("eval_cc300_compressor_manual.pdf", 1)], ["separator"]),
    ("D05", "dev", "paraphrase", "At what temperature does the compressor shut itself down on heat?", [("eval_cc300_compressor_manual.pdf", 2)], ["115"]),
    ("D06", "dev", "paraphrase", "What should I do about a conveyor belt that keeps wandering to one side?", [("eval_cv400_conveyor_manual.pdf", 1)], ["idler"]),
    ("D07", "dev", "incident", "Which past incident involved a seized idler roller on conveyor CV-401?", [("eval_incident_history.csv", "INC-2025-1001")], ["INC-2025-1001"]),
    ("D08", "dev", "keyword", "How many heat exchanger tubes can be plugged?", [("eval_ht600_heat_exchanger_manual.pdf", 2)], ["10"]),
    ("D09", "dev", "paraphrase", "Gear teeth play: what backlash is acceptable?", [("eval_gb500_gearbox_manual.pdf", 3)], ["0.15", "0.25"]),
    ("D10", "dev", "paraphrase", "How much misalignment can the pump coupling tolerate?", [("eval_cp200_pump_manual.pdf", 4)], ["0.05"]),
    ("D11", "dev", "paraphrase", "Why does the motor keep tripping on overload even with the right setting?", [("eval_em55_motor_manual.pdf", 4)], ["imbalance"]),
    ("D12", "dev", "keyword", "When should the compressor air intake filter be changed?", [("eval_cc300_compressor_manual.pdf", 3)], ["vacuum"]),
    ("T01", "test", "keyword", "What grease should be used for the CP-200 pump bearings?", [("eval_cp200_pump_manual.pdf", 1)], ["nlgi 2"]),
    ("T02", "test", "paraphrase", "How many drops a minute of seal leakage means the seal must be replaced?", [("eval_cp200_pump_manual.pdf", 2)], ["10"]),
    ("T03", "test", "paraphrase", "What happens if the pump runs without liquid in the casing?", [("eval_cp200_pump_manual.pdf", 2)], ["30 seconds"]),
    ("T04", "test", "paraphrase", "How much suction margin do I need to avoid the inlet rattling problem?", [("eval_cp200_pump_manual.pdf", 3)], ["0.5"]),
    ("T05", "test", "paraphrase", "What is the correct way to bring the pump up to pressure when starting it?", [("eval_cp200_pump_manual.pdf", 5)], ["10 percent"]),
    ("T06", "test", "keyword", "What are the alarm and trip vibration levels for the pump?", [("eval_cp200_pump_manual.pdf", 6)], ["4.5", "7.1"]),
    ("T07", "test", "paraphrase", "What is the usual reason an electric motor's windings run hot?", [("eval_em55_motor_manual.pdf", 1)], ["fins"]),
    ("T08", "test", "paraphrase", "What does a squealing noise from a motor bearing tell me?", [("eval_em55_motor_manual.pdf", 3)], ["lubricant"]),
    ("T09", "test", "paraphrase", "How much should motor output be reduced in a hot room?", [("eval_em55_motor_manual.pdf", 5)], ["2 percent"]),
    ("T10", "test", "keyword", "What full load current is the motor thermal overload based on?", [("eval_em55_motor_manual.pdf", 4)], ["98"]),
    ("T11", "test", "paraphrase", "How often should the compressor oil separator be swapped?", [("eval_cc300_compressor_manual.pdf", 1)], ["8,000"]),
    ("T12", "test", "paraphrase", "What can cause the compressor outlet to run too hot?", [("eval_cc300_compressor_manual.pdf", 2)], ["oil cooler"]),
    ("T13", "test", "paraphrase", "The compressor delivers less air and the middle stage is hot; what part has failed?", [("eval_cc300_compressor_manual.pdf", 4)], ["valve plate"]),
    ("T14", "test", "keyword", "What torque applies to the compressor foundation bolts?", [("eval_cc300_compressor_manual.pdf", 5)], ["120"]),
    ("T15", "test", "paraphrase", "Which gear oil grade goes in the conveyor gearbox and how often is it changed?", [("eval_cv400_conveyor_manual.pdf", 2)], ["vg 220", "5,000"]),
    ("T16", "test", "paraphrase", "When is a conveyor roller considered bad enough to swap?", [("eval_cv400_conveyor_manual.pdf", 3)], ["20 c"]),
    ("T17", "test", "paraphrase", "What causes the conveyor motor to trip on overload?", [("eval_cv400_conveyor_manual.pdf", 4)], ["chute"]),
    ("T18", "test", "paraphrase", "Oil is dripping near the gearbox output shaft; what should I check first?", [("eval_gb500_gearbox_manual.pdf", 1)], ["breather"]),
    ("T19", "test", "keyword", "What is the maximum sump temperature for the GB-500 gearbox?", [("eval_gb500_gearbox_manual.pdf", 2)], ["90"]),
    ("T20", "test", "paraphrase", "How accurate does the gearbox input coupling alignment need to be?", [("eval_gb500_gearbox_manual.pdf", 4)], ["0.08"]),
    ("T21", "test", "paraphrase", "When does the heat exchanger need to be cleaned?", [("eval_ht600_heat_exchanger_manual.pdf", 1)], ["5 c"]),
    ("T22", "test", "paraphrase", "How do I detect a leaking tube in the cooler?", [("eval_ht600_heat_exchanger_manual.pdf", 2)], ["conductivity"]),
    ("T23", "test", "keyword", "What differential pressure is the limit for the heat exchanger?", [("eval_ht600_heat_exchanger_manual.pdf", 3)], ["0.8"]),
    ("T24", "test", "paraphrase", "How long should the cleaning solution circulate and what pH is the target after rinsing?", [("eval_ht600_heat_exchanger_manual.pdf", 4)], ["4 hours", "6.5"]),
    ("T25", "test", "incident", "What was the root cause when compressor CC-301 blew oil into the air line after 9,500 hours?", [("eval_incident_history.csv", "INC-2025-1002")], ["separator"]),
    ("T26", "test", "incident", "How was the blocked-fin overheating on motor M-202 resolved?", [("eval_incident_history.csv", "INC-2025-1003")], ["cleaned"]),
    ("T27", "test", "incident", "Which incident dealt with a pump seal that leaked after being run dry at start-up?", [("eval_incident_history.csv", "INC-2025-1004")], ["INC-2025-1004"]),
    ("T28", "test", "incident", "What fixed the oil leak at the mixer gearbox output shaft?", [("eval_incident_history.csv", "INC-2025-1005")], ["breather"]),
    ("T29", "test", "incident", "Was there ever a conductivity rise in the cooling water of the process cooler, and what was done?", [("eval_incident_history.csv", "INC-2025-1012")], ["tubes"]),
    ("T30", "test", "incident", "What caused the soft foot related vibration on pump P-103?", [("eval_incident_history.csv", "INC-2025-1010")], ["foot"]),
    ("T31", "test", "incident", "Which incident involved moisture in the motor windings after flooding?", [("eval_incident_history.csv", "INC-2025-1008")], ["INC-2025-1008"]),
    ("T32", "test", "incident", "How was the gear noise with high backlash on the crusher gearbox resolved?", [("eval_incident_history.csv", "INC-2025-1015")], ["gear set"]),
    ("T33", "test", "paraphrase", "What was the P-103 vibration reading in the Q2 2026 inspection?", [("eval_inspection_2026q2.pdf", 1)], ["6.9"]),
    ("T34", "test", "paraphrase", "What backlash was measured on the crusher gearbox in the Q3 2026 inspection?", [("eval_inspection_2026q3.pdf", 1)], ["0.38"]),
    ("T35", "test", "paraphrase", "How hot was compressor CC-301's discharge in the Q3 2026 inspection?", [("eval_inspection_2026q3.pdf", 2)], ["96"]),
    ("T36", "test", "paraphrase", "What did the Q2 2026 inspection find on conveyor CV-402's gearbox?", [("eval_inspection_2026q2.pdf", 2)], ["oil level"]),
]
UNANSWERABLE = [
    ("DU1", "dev", "What is the warranty period of the CP-200 pump?"), ("DU2", "dev", "Who is the plant safety manager?"),
    ("DU3", "dev", "What is the price of the bearing set PN-4417?"), ("DU4", "dev", "How do I configure the SCADA historian?"),
    ("TU1", "test", "What colour is the CP-200 pump painted?"), ("TU2", "test", "Which vendor supplies the plant forklifts?"),
    ("TU3", "test", "What is the maximum noise level allowed in the canteen?"), ("TU4", "test", "How do I reset my email password?"),
    ("TU5", "test", "What were last quarter's production totals?"), ("TU6", "test", "What is the serial number of the CC-300 compressor?"),
    ("TU7", "test", "Is the HT-600 covered by an extended service contract?"), ("TU8", "test", "How tall is the cooling tower?"),
]

# Fault reports for structured extraction: (id, text, asset_id|None, category, vibration|None, smoke_or_fire)
REPORTS = [
    ("R01", "Pump P-101 is vibrating hard at the drive end, reading 8.4 mm/s, with a grinding noise.", "P-101", "mechanical_vibration", 8.4, False),
    ("R02", "Idler roller on CV-401 is squealing loudly and the belt edge is fraying.", "CV-401", "noise", None, False),
    ("R03", "Smoke is coming from the terminal box of motor M-202, strong burning smell.", "M-202", "electrical_fault", None, True),
    ("R04", "Compressor CC-301 discharge temperature is climbing and the machine is running too hot.", "CC-301", "overheating", None, False),
    ("R05", "Oil is dripping from the output shaft of gearbox G-501.", "G-501", "leak", None, False),
    ("R06", "P-102 shows vibration of 5.2 mm/s at the non-drive end.", "P-102", "mechanical_vibration", 5.2, False),
    ("R07", "Heat exchanger H-601 pressure drop is higher than normal and cooling is poor.", "H-601", "performance_degradation", None, False),
    ("R08", "Motor M-201 keeps tripping on thermal overload every few minutes.", "M-201", "electrical_fault", None, False),
    ("R09", "Mechanical seal on P-104 is leaking steadily, a puddle under the pump.", "P-104", "leak", None, False),
    ("R10", "Gearbox G-502 is making a rattling noise under load.", "G-502", "noise", None, False),
    ("R11", "CV-402 gearbox is whining and the oil sight glass looks low.", "CV-402", "noise", None, False),
    ("R12", "Pump P-103 vibration measured 12.5 mm/s, severe shaking of the base plate.", "P-103", "mechanical_vibration", 12.5, False),
    ("R13", "Fan motor M-203 is very hot to touch and smells like it is overheating.", "M-203", "overheating", None, False),
    ("R14", "Compressor CC-302 output is low and air pressure drop is visible at the receiver.", "CC-302", "performance_degradation", None, False),
    ("R15", "Fire in the control cabinet next to CC-301! Flames visible.", "CC-301", "electrical_fault", None, True),
    ("R16", "P-101 vibration of 7.5 mm/s at the drive end bearing housing.", "P-101", "mechanical_vibration", 7.5, False),
    ("R17", "Small oil leak at the shaft seal of H-601 circulation pump skid.", "H-601", "leak", None, False),
    ("R18", "Belt on CV-401 is running off to one side and rubbing the frame.", "CV-401", "other", None, False),
    ("R19", "P-102 pump vibrating with 8.9 millimetres per second at the bearing.", "P-102", "mechanical_vibration", 8.9, False),
    ("R20", "Gearbox G-501 sump is running hot, over 95 degrees.", "G-501", "overheating", None, False),
    ("R21", "There is a strange noise somewhere in the plant but I cannot tell where it comes from.", None, "noise", None, False),
    ("R22", "Motor M-202 trips its breaker when starting, short circuit suspected.", "M-202", "electrical_fault", None, False),
    ("R23", "Compressor CC-301 vibration reading 4.8 mm/s, slightly up from last week.", "CC-301", "mechanical_vibration", 4.8, False),
    ("R24", "Pump P-104 is running but flow is lower than usual and the gauge pressure has fallen.", "P-104", "performance_degradation", None, False),
]


def write_pdf(path: Path, title: str, pages):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    for heading, body in pages:
        y = 800
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, f"{title} - {heading}"[:95])
        y -= 30
        c.setFont("Helvetica", 10.5)
        for line in textwrap.wrap(body, 92):
            c.drawString(50, y, line)
            y -= 15
        c.showPage()
    c.save()


def write_csv(path: Path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    for name, (title, pages) in {**MANUALS, **INSPECTIONS}.items():
        write_pdf(DOCS / name, title, pages)
    write_csv(DOCS / "eval_equipment_register.csv", ["equipment_id", "name", "model", "location"], REGISTER)
    incidents = [[i, "2025-01-15", e, c, d, r, s] for i, e, c, d, r, s in TARGETED_INCIDENTS]
    for n, (e, c, d, r, s) in enumerate(FILLER, start=1):
        incidents.append([f"INC-2025-{2000 + n}", "2025-06-01", e, c, d, r, s])
    write_csv(DOCS / "eval_incident_history.csv",
              ["incident_id", "date", "equipment_id", "category", "description", "root_cause", "resolution"], incidents)
    with (OUT / "queries.jsonl").open("w", encoding="utf-8") as fh:
        for qid, split, qtype, query, rel, facts in Q:
            fh.write(json.dumps({"id": qid, "split": split, "answerable": True, "type": qtype, "query": query,
                                 "relevant": [{"file": f, "unit": u} for f, u in rel], "key_facts": facts}) + "\n")
        for qid, split, query in UNANSWERABLE:
            fh.write(json.dumps({"id": qid, "split": split, "answerable": False, "type": "unanswerable",
                                 "query": query, "relevant": [], "key_facts": []}) + "\n")
    with (OUT / "reports.jsonl").open("w", encoding="utf-8") as fh:
        for rid, text, asset, cat, vib, smoke in REPORTS:
            fh.write(json.dumps({"id": rid, "text": text, "asset_id": asset, "category": cat,
                                 "vibration_mm_s": vib, "smoke_or_fire": smoke}) + "\n")
    files = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "build_dataset.py"
                   and p.name != "dataset_manifest.json" and p.suffix != ".pdf")
    digest = hashlib.sha256()
    for p in files:
        digest.update(p.name.encode() + p.read_bytes())
    manifest = {
        "name": "apex-eval-v1", "synthetic": True, "fictional": True,
        "documents": sorted(p.name for p in DOCS.iterdir()),
        "queries": {"answerable_dev": sum(1 for q in Q if q[1] == "dev"),
                    "answerable_test": sum(1 for q in Q if q[1] == "test"),
                    "unanswerable_dev": sum(1 for q in UNANSWERABLE if q[1] == "dev"),
                    "unanswerable_test": sum(1 for q in UNANSWERABLE if q[1] == "test")},
        "fault_reports": len(REPORTS),
        "text_files_sha256": digest.hexdigest(),
        "relevance_unit": "(filename, page) for PDFs; (filename, record_id) for CSV rows",
        "splits": "dev: calibrate evidence threshold only; test: held-out reported results",
    }
    (OUT / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest["queries"]), "reports:", len(REPORTS))


if __name__ == "__main__":
    main()
