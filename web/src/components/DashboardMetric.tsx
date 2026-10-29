import { Icon } from "./ui";

export function DashboardMetric({ label, value, detail, icon, accent = false }: {
  label: string;
  value: string;
  detail: string;
  icon: string;
  accent?: boolean;
}) {
  return (
    <div className={`dashboard-metric${accent ? " is-accent" : ""}`}>
      <dt><span>{label}</span><Icon name={icon} size={17} /></dt>
      <dd><span className="dashboard-metric-value">{value}</span><span className="dashboard-metric-detail" title={detail}>{detail}</span></dd>
    </div>
  );
}
