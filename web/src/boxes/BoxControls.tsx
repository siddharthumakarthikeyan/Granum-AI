/** Display options for boxes, shared by the image inspector and grid thumbnails. */

import { useStore } from "../store/store";
import { boxColumns, ROLE_NAMES, ROLE_STYLE, type BoxRole } from "./model";

export function BoxControls({ compact = false }: { compact?: boolean }) {
  const display = useStore((s) => s.boxDisplay);
  const setDisplay = useStore((s) => s.setBoxDisplay);
  const columns = useStore((s) => s.columns);
  const { truth, predicted } = boxColumns(columns);
  if (!truth && !predicted) return null;

  const numericProperties = Object.entries(predicted?.instance_properties ?? truth?.instance_properties ?? {})
    .filter(([, kind]) => kind.startsWith("float"))
    .map(([name]) => name);

  return (
    <span className={`box-controls${compact ? " compact" : ""}`}>
      <span className="layer-toggles" role="group" aria-label="Box layers">
        {truth && (
          <button
            className={`layer-toggle${display.showTruth ? " on" : ""}`}
            aria-pressed={display.showTruth}
            onClick={() => setDisplay({ showTruth: !display.showTruth })}
            title="Show labelled boxes"
          >
            <i className="layer-swatch truth" />Labels
          </button>
        )}
        {predicted && (
          <button
            className={`layer-toggle${display.showPredicted ? " on" : ""}`}
            aria-pressed={display.showPredicted}
            onClick={() => setDisplay({ showPredicted: !display.showPredicted })}
            title="Show predicted boxes"
          >
            <i className="layer-swatch predicted" />Predictions
          </button>
        )}
      </span>
      {predicted && (
        <label className="control-field" title="Hide predictions below this confidence">
          <span>Conf ≥</span>
          <input
            type="range" min={0} max={1} step={0.05} value={display.minConfidence}
            onChange={(e) => setDisplay({ minConfidence: Number(e.target.value) })}
          />
          <span className="num">{display.minConfidence.toFixed(2)}</span>
        </label>
      )}
      {!compact && (
        <>
          <label className="control-field">
            <span>Text</span>
            <select value={display.annotate} onChange={(e) => setDisplay({ annotate: e.target.value as typeof display.annotate })}>
              <option value="all">All boxes</option>
              <option value="selected">Selected box</option>
              <option value="none">None</option>
            </select>
          </label>
          <label className="control-field">
            <span>Colour</span>
            <select value={display.colorBy} onChange={(e) => setDisplay({ colorBy: e.target.value as typeof display.colorBy })}>
              <option value="role">Match result</option>
              <option value="class">Class</option>
            </select>
          </label>
          {numericProperties.length > 0 && (
            <label className="control-field">
              <span>Opacity</span>
              <select value={display.opacityBy ?? ""} onChange={(e) => setDisplay({ opacityBy: e.target.value || null })}>
                <option value="">Fixed</option>
                {numericProperties.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          )}
        </>
      )}
    </span>
  );
}

export function RoleLegend({ roles }: { roles: BoxRole[] }) {
  return (
    <span className="role-legend">
      {roles.map((role) => (
        <span key={role} title={ROLE_STYLE[role].label}>
          <svg width="18" height="10" aria-hidden="true">
            <rect x="1" y="1" width="16" height="8" fill="none" stroke={ROLE_STYLE[role].color}
              strokeWidth="1.5" strokeDasharray={ROLE_STYLE[role].dash ?? undefined} />
          </svg>
          {ROLE_NAMES[role]}
        </span>
      ))}
    </span>
  );
}
