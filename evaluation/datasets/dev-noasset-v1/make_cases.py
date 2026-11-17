"""Development-only cases for the 'model invents an asset id' failure (author-written on 2026-11-13; NOT independent, NOT a confirmation set).

Why this exists: the consumed held-out split showed two reports with no identifiable equipment where the model invented an asset id (raw schema validity 18 of 20). The development split of
eval-v2 has NO such cases, and the held-out and challenge splits are consumed and must not be used for tuning, so these new reports are the only legitimate tuning material for that failure.
They were written fresh here (not copied or paraphrased from any consumed case) and are frozen once an experiment has used them: any later change must create dev-noasset-v2.
Run: python evaluation/datasets/dev-noasset-v1/make_cases.py  (writes cases.jsonl and MANIFEST.sha256)"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# no equipment id anywhere in the report: the correct asset_id is null
NO_ASSET = [
    "The big pump near the loading dock is shaking badly and making a grinding noise.",
    "Something in the boiler room smells like burning insulation, please check it today.",
    "Oil is dripping from the gearbox at the end of the packing line.",
    "The compressor in the east building keeps tripping its breaker every few minutes.",
    "A conveyor belt on the second floor is squealing and running slowly.",
    "Water is leaking from a pipe joint above the control room door.",
    "The cooling fan on the roof is rattling loudly since the storm.",
    "One of the pumps in the pump house is much hotter than the others.",
    "Pressure has dropped on the main air line and the tools are weak.",
    "The mixer in the paint shop stopped suddenly and will not restart.",
    "Strange humming from the electrical cabinet by the back entrance, a bit of smoke too.",
    "The heater in the warehouse is not producing any heat today.",
    "We hear a loud bang from the press machine every time it cycles.",
    "The forklift charger smells hot and the display is flickering.",
    "A valve near the tank farm is weeping fluid onto the floor.",
    "The old lathe vibrates at high speed and leaves marks on the parts.",
]
# a real-looking id is present: the correct asset_id is that id, exactly as written
WITH_ASSET = [
    ("Pump XJ-204 is vibrating strongly at the drive end.", "XJ-204"),
    ("Gearbox GB-77 is leaking oil from the output seal.", "GB-77"),
    ("Compressor K-12 trips its breaker after about five minutes of running.", "K-12"),
    ("Fan F-3301 is rattling and the housing feels hot.", "F-3301"),
    ("Conveyor CV-88 squeals and runs slowly since this morning.", "CV-88"),
    ("There is a burning smell from panel EP-409 and some smoke.", "EP-409"),
    ("Valve V-1520 is weeping fluid onto the floor.", "V-1520"),
    ("Mixer MX-6 stopped suddenly and will not restart.", "MX-6"),
    ("Heater HT-21 produces no heat at all today.", "HT-21"),
    ("Press PR-300 makes a loud bang every cycle.", "PR-300"),
    ("Pump P-908 has pressure dropping on the discharge side.", "P-908"),
    ("The lathe LT-14 vibrates at high speed and marks the parts.", "LT-14"),
    ("Charger CH-5 smells hot and its display flickers, near pump P-77 in the same bay.", "CH-5"),
    ("Tank T-02 valve is leaking; the neighbouring tank T-03 is fine.", "T-02"),
]


def main() -> None:
    rows = [{"id": f"NA-{i:02d}", "kind": "no_asset", "text": t, "expected_asset": None} for i, t in enumerate(NO_ASSET, 1)]
    rows += [{"id": f"WA-{i:02d}", "kind": "with_asset", "text": t, "expected_asset": a} for i, (t, a) in enumerate(WITH_ASSET, 1)]
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    (HERE / "cases.jsonl").write_text(body, encoding="utf-8", newline="\n")
    (HERE / "MANIFEST.sha256").write_text(hashlib.sha256(body.encode()).hexdigest() + "  cases.jsonl\n", encoding="utf-8", newline="\n")
    print(len(rows), hashlib.sha256(body.encode()).hexdigest())


if __name__ == "__main__":
    main()
