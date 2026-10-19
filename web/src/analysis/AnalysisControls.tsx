import { useState } from "react";
import { Modal } from "../components/Modal";
import { useStore } from "../store/store";
import { OPERATIONS, type Operation } from "./virtualColumns";
import { reconcileAnalysis } from "./state";
import { ProjectionDialog } from "./ProjectionDialog";
import { LandmarkDialog } from "./LandmarkDialog";
import { landmarkIndices } from "./landmarks";
import { captureWorkflow, compatibleColumns, parseWorkflow, readWorkflows, validateWorkflow, workflowView, writeWorkflows, type AnalysisWorkflow } from "./workflows";

const message = (error: unknown) => error instanceof Error ? error.message : String(error);

export function AnalysisControls() {
  const [dialog, setDialog] = useState<"calculate" | "workflows" | "projection" | "landmarks" | null>(null);
  const hasEmbeddings = useStore(s => s.columns.some(c => c.kind === "embedding"));
  const hasLandmarks = useStore(s => s.columns.some(c => landmarkIndices(c).length > 0));
  const hasEdits = useStore(s => s.undoStack.length > 0);
  const error = useStore(s => s.analysisError);
  return <>
    <button className="button subtle" onClick={() => setDialog("calculate")}>Calculate</button>
    <button className="button subtle" onClick={() => setDialog("workflows")}>Workflows</button>
    {hasEmbeddings && <button className="button subtle" disabled={hasEdits} title={hasEdits ? "Save your edits before creating a projection" : "Explore embeddings in two or three dimensions"} onClick={() => setDialog("projection")}>Embeddings</button>}
    {hasLandmarks && <button className="button subtle" onClick={() => setDialog("landmarks")}>Landmarks</button>}
    {error && <span role="alert" title={error}>Calculation unavailable: {error}</span>}
    {dialog === "calculate" && <CalculateDialog onClose={() => setDialog(null)} />}
    {dialog === "workflows" && <WorkflowsDialog onClose={() => setDialog(null)} />}
    {dialog === "projection" && <ProjectionDialog onClose={() => setDialog(null)} />}
    {dialog === "landmarks" && <LandmarkDialog onClose={() => setDialog(null)} />}
  </>;
}

function CalculateDialog({ onClose }: { onClose: () => void }) {
  const columns = useStore(s => s.columns);
  const definitions = useStore(s => s.virtualColumns);
  const setColumns = useStore(s => s.setVirtualColumns);
  const available = compatibleColumns(columns);
  const [name, setName] = useState("");
  const [operation, setOperation] = useState<Operation>("divide");
  const [inputs, setInputs] = useState<string[]>(() => {
    const selected = [...useStore.getState().selection.columns];
    return [selected[0] ?? available[0]?.name ?? "", selected[1] ?? available[1]?.name ?? ""];
  });
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const [orderBy, setOrderBy] = useState("epoch");
  const [error, setError] = useState<string | null>(null);
  const binary = ["add", "subtract", "multiply", "divide", "power", "distance", "dot", "equal", "greater", "less"].includes(operation);
  const variadic = ["sum", "mean", "min", "max"].includes(operation);
  const temporal = ["previous", "next", "difference", "cumulative_sum"].includes(operation);
  const grouped = temporal || operation.startsWith("group_") || ["rank", "occurrence", "standardize"].includes(operation);
  const count = binary ? 2 : variadic ? Math.max(1, inputs.length) : 1;
  const options = available.map(c => <option key={c.name} value={c.name}>{c.name}</option>);
  const add = () => {
    const problem = setColumns([...definitions, { name: name.trim(), operation, inputs: inputs.slice(0, count),
      groupBy: grouped ? groupBy : [], ...(temporal ? { orderBy } : {}) }]);
    setError(problem);
    if (!problem) setName("");
  };
  return <Modal title="Calculated columns" onClose={onClose} width={580} footer={<>
    <span className="spacer" /><button onClick={onClose}>Close</button><button className="primary" onClick={add} disabled={!name.trim()}>Add calculation</button>
  </>}>
    <p className="muted">Calculations update with edits and use all loaded rows. Save a workflow to reuse them.</p>
    <label className="field"><span>Column name</span><input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. loss_per_object" /></label>
    <label className="field"><span>Operation</span><select value={operation} onChange={e => setOperation(e.target.value as Operation)}>
      {Object.entries(OPERATIONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select></label>
    {Array.from({ length: count }, (_, i) => <label className="field" key={i}><span>Input {i + 1}</span>
      <select value={inputs[i] ?? ""} onChange={e => setInputs(old => { const next = [...old]; next[i] = e.target.value; return next; })}>
        <option value="">Choose a column</option>{options}
      </select>
    </label>)}
    {variadic && <button onClick={() => setInputs(old => [...old, ""])} disabled={inputs.length >= 16}>Add input</button>}
    {grouped && <label className="field"><span>Group by (optional; Ctrl/Cmd to select several)</span>
      <select multiple value={groupBy} onChange={e => setGroupBy([...e.target.selectedOptions].map(o => o.value))}>
        <option value="_src">Source dataset</option>{options}
      </select>
    </label>}
    {temporal && <label className="field"><span>Order observations by</span><select value={orderBy} onChange={e => setOrderBy(e.target.value)}>
      <option value="">Choose a numeric column</option>{options}<option value="_row">Original row</option>
    </select></label>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {definitions.length > 0 && <div aria-label="Existing calculations">{definitions.map((c, i) => <div key={c.name} style={{ display: "flex", gap: 8, marginTop: 8 }}>
      <span className="mono">{c.name} = {c.operation}({c.inputs.join(", ")})</span><span className="spacer" />
      <button aria-label={`Remove ${c.name}`} onClick={() => setError(setColumns(definitions.filter((_, at) => at !== i)))}>Remove</button>
    </div>)}</div>}
  </Modal>;
}

function WorkflowsDialog({ onClose }: { onClose: () => void }) {
  const [workflows, setWorkflows] = useState<AnalysisWorkflow[]>(() => { try { return readWorkflows(); } catch { return []; } });
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = (next: AnalysisWorkflow[]) => { writeWorkflows(next); setWorkflows(next); };
  const run = (action: () => void) => { try { action(); setError(null); } catch (e) { setError(message(e)); } };
  const apply = (workflow: AnalysisWorkflow) => run(() => {
    const state = useStore.getState();
    validateWorkflow(workflow, state);
    const calculated = reconcileAnalysis(state, { virtualColumns: workflow.calculations });
    if (calculated.analysisError) throw new Error(calculated.analysisError);
    const view = workflowView(workflow, { ...state, ...calculated });
    // Validate everything before replacing the view; a failed import changes nothing.
    useStore.setState({ ...calculated, ...view });
    onClose();
  });
  return <Modal title="Analysis workflows" onClose={onClose} width={620} footer={<>
    <label className="button">Import JSON<input type="file" accept="application/json,.json" style={{ display: "none" }} onChange={async e => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        if (file.size > 2 * 1024 * 1024) throw new Error("Workflow files must be smaller than 2 MiB");
        const imported = parseWorkflow(JSON.parse(await file.text()));
        if (workflows.some(w => w.name === imported.name)) throw new Error("A workflow with that name already exists");
        save([...workflows, imported]); setError(null);
      } catch (err) { setError(message(err)); }
      e.target.value = "";
    }} /></label><span className="spacer" /><button onClick={onClose}>Close</button>
  </>}>
    <p className="muted">Save calculations, charts, filters and sorting. Export a workflow to share the analysis setup.</p>
    <label className="field"><span>Name this setup</span><input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. High-loss samples across epochs" /></label>
    <button disabled={!name.trim()} onClick={() => run(() => {
      if (workflows.some(w => w.name === name.trim())) throw new Error("Choose a different name or remove the existing workflow");
      save([...workflows, captureWorkflow(useStore.getState(), name)]); setName("");
    })}>Save current setup</button>
    {workflows.map((workflow, i) => <div key={workflow.name} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}>
      <span>{workflow.name}</span><span className="spacer" /><button onClick={() => apply(workflow)}>Apply</button>
      <button onClick={() => run(() => {
        const url = URL.createObjectURL(new Blob([JSON.stringify(workflow, null, 2)], { type: "application/json" }));
        const link = document.createElement("a"); link.href = url; link.download = `${workflow.name.replace(/[^\w-]+/g, "-")}.granum-workflow.json`;
        link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      })}>Export</button>
      <button onClick={() => run(() => save(workflows.filter((_, at) => at !== i)))}>Remove</button>
    </div>)}
    {error && <p className="form-error" role="alert">{error}</p>}
  </Modal>;
}
