import { useId } from "react";
import { Field } from "./ui";

/** Mirror of the API's StructuredObservation request schema. There is deliberately no field for trust status, reviewer, provenance, sensor authentication or simulation. */
export type MeasurementType = "vibration" | "brake_pressure" | "coolant_temperature";
export interface ObservationRow {
  key: number;
  asset_id: string;
  measurement_type: MeasurementType;
  value: string;
  unit: string;
  observed_at: string;
  source: string;
}
export interface ObservationPayload {
  asset_id: string;
  measurement_type: MeasurementType;
  value: number;
  unit: string;
  observed_at?: string;
  source?: string;
}

export const TYPES: { value: MeasurementType; label: string; unit: string }[] = [
  { value: "vibration", label: "Vibration", unit: "mm/s" },
  { value: "brake_pressure", label: "Brake pressure", unit: "psi" },
  { value: "coolant_temperature", label: "Coolant temperature", unit: "C" },
];
export const MAX_ROWS = 20;
/** Structured values are typed numbers, not text: one explicit format (optional minus, digits, optional dot decimals). A comma is refused rather than guessed, because "8,4" and "8,400" differ by locale. */
const NUMBER = /^-?\d+(\.\d+)?$/;

export const newRow = (key: number, asset = ""): ObservationRow => ({ key, asset_id: asset, measurement_type: "vibration", value: "", unit: "mm/s", observed_at: "", source: "" });

export function validateRow(r: ObservationRow): Record<string, string> {
  const e: Record<string, string> = {};
  if (r.asset_id.trim().length < 2 || r.asset_id.trim().length > 40) e.asset_id = "Enter the asset id (2 to 40 characters).";
  if (!r.value.trim()) e.value = "Enter the numeric value.";
  else if (r.value.includes(",")) e.value = "Use a decimal point, not a comma (for example 8.4).";
  else if (!NUMBER.test(r.value.trim()) || !Number.isFinite(Number(r.value))) e.value = "Enter a plain number such as 8.4.";
  if (!r.unit.trim() || r.unit.trim().length > 12) e.unit = "Enter the unit (up to 12 characters).";
  if (r.source.length > 80) e.source = "At most 80 characters.";
  if (r.observed_at && Number.isNaN(Date.parse(r.observed_at))) e.observed_at = "Enter a valid date and time.";
  return e;
}

export function toPayload(r: ObservationRow): ObservationPayload {
  const p: ObservationPayload = { asset_id: r.asset_id.trim(), measurement_type: r.measurement_type, value: Number(r.value.trim()), unit: r.unit.trim() };
  if (r.observed_at) p.observed_at = new Date(r.observed_at).toISOString();
  if (r.source.trim()) p.source = r.source.trim();
  return p;
}

interface Props {
  rows: ObservationRow[];
  errors: Record<number, Record<string, string>>;
  disabled?: boolean;
  onChange: (rows: ObservationRow[]) => void;
}

export default function ObservationForm({ rows, errors, disabled, onChange }: Props) {
  const heading = useId();
  const update = (key: number, patch: Partial<ObservationRow>) => onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <fieldset className="callout" aria-labelledby={heading}>
      <legend id={heading}>Structured observations (optional)</legend>
      <p className="muted small">Enter a reading you took from an instrument or record. It is stored as a <strong>submitted observation awaiting verification</strong>: it does not change the priority until a supervisor other than you verifies it. Observations can only be added when the report is analysed.</p>
      {rows.map((r, i) => {
        const e = errors[r.key] ?? {};
        return (
          <div key={r.key} className="row" role="group" aria-label={`Observation ${i + 1}`}>
            <Field label="Measurement type">
              {(p) => <select {...p} value={r.measurement_type} disabled={disabled} onChange={(ev) => {
                const type = ev.target.value as MeasurementType;
                update(r.key, { measurement_type: type, unit: TYPES.find((t) => t.value === type)?.unit ?? r.unit });
              }}>{TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select>}
            </Field>
            <Field label="Asset" error={e.asset_id}>{(p) => <input {...p} value={r.asset_id} disabled={disabled} maxLength={40} onChange={(ev) => update(r.key, { asset_id: ev.target.value })} />}</Field>
            <Field label="Value" error={e.value}>{(p) => <input {...p} inputMode="decimal" value={r.value} disabled={disabled} onChange={(ev) => update(r.key, { value: ev.target.value })} />}</Field>
            <Field label="Unit" error={e.unit}>{(p) => <input {...p} value={r.unit} disabled={disabled} maxLength={12} onChange={(ev) => update(r.key, { unit: ev.target.value })} />}</Field>
            <Field label="Observed at (optional)" error={e.observed_at}>{(p) => <input {...p} type="datetime-local" value={r.observed_at} disabled={disabled} onChange={(ev) => update(r.key, { observed_at: ev.target.value })} />}</Field>
            <Field label="Source reference (recommended)" error={e.source} hint="For example the gauge, printout or work order you read it from.">{(p) => <input {...p} value={r.source} disabled={disabled} maxLength={80} onChange={(ev) => update(r.key, { source: ev.target.value })} />}</Field>
            <button type="button" className="secondary" disabled={disabled} onClick={() => onChange(rows.filter((x) => x.key !== r.key))}>Remove observation {i + 1}</button>
          </div>
        );
      })}
      <button type="button" className="secondary" disabled={disabled || rows.length >= MAX_ROWS} onClick={() => onChange([...rows, newRow(Math.max(0, ...rows.map((r) => r.key)) + 1)])}>
        {rows.length ? "Add another observation" : "Add a structured observation"}
      </button>
    </fieldset>
  );
}
