/** A past import: the report as it was, the options applied, and what they changed. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ImportResult, PreflightReport } from "../api/types";
import { EmptyState, PageHeader, VerdictBadge, formatWhen } from "../components/ui";
import { routeHref } from "../router";
import { ReportView } from "./ReportView";

export function SavedReportPage({ project, id }: { project: string; id: string }) {
  const [data, setData] = useState<{ report: PreflightReport; import: ImportResult } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.importReport(project, id).then(setData).catch((e: Error) => setError(e.message));
  }, [project, id]);

  if (error) {
    return <div className="page"><EmptyState title="This report could not be loaded"><p>{error}</p></EmptyState></div>;
  }
  if (!data) return <div className="page"><PageHeader title="Import report" subtitle="Loading" /></div>;

  const { report, import: result } = data;
  return (
    <div className="page page-wide">
      <PageHeader
        back={{ href: routeHref({ name: "overview", project }), label: project }}
        title={`Import of ${report.sources.map((s) => s.split).join(" and ")}`}
        subtitle={
          <>
            Checked {formatWhen(report.created)} from <span className="mono">{report.sources[0]?.annotations.split("/").slice(-3, -1).join("/")}</span>.
            The options shown are the ones applied.
          </>
        }
        actions={<VerdictBadge verdict={report.verdict} />}
      />
      <div className="report-tables">
        {result.tables.map((table) => (
          <a key={table.url} className="button" href={routeHref({ name: "table", project, url: table.url })}>
            Open {table.split}
          </a>
        ))}
      </div>
      <ReportView report={report} choices={result.resolutions} effects={result.effects} />
    </div>
  );
}
