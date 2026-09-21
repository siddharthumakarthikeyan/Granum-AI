/** Small shared pieces of the product shell: icons, the mark, status badges, formatting. */

import { useEffect, useId, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Severity, Verdict } from "../api/types";
import { GLOSSARY } from "../copy/plain";

const PATHS: Record<string, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="8" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="15" width="7" height="6" rx="1.5" /></>,
  datasets: <><path d="M12 3 3 7.5l9 4.5 9-4.5L12 3Z" /><path d="m3 12 9 4.5 9-4.5" /><path d="m3 16.5 9 4.5 9-4.5" /></>,
  runs: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  findings: <><path d="M10 4H5a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4" strokeDasharray="2.5 2" /><circle cx="15" cy="11" r="5" /><path d="m18.6 14.6 3.4 3.4" /></>,
  import: <><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></>,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />,
  file: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" /><path d="M14 3v5h5" /></>,
  chevron: <path d="m9 6 6 6-6 6" />,
  back: <path d="m15 6-6 6 6 6" />,
  up: <path d="M12 19V5M5 12l7-7 7 7" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  block: <><circle cx="12" cy="12" r="9" /><path d="m8.5 8.5 7 7m0-7-7 7" /></>,
  warn: <><path d="M10.3 3.9 2.4 17.6A2 2 0 0 0 4.1 20.6h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  open: <><path d="M14 4h6v6" /><path d="M20 4 11 13" /><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>,
  shield: <path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6l-8-3Z" />,
  table: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 10v10" /></>,
  lock: <><rect x="5" y="11" width="14" height="9" rx="1.5" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  unlock: <><rect x="5" y="11" width="14" height="9" rx="1.5" /><path d="M8 11V8a4 4 0 0 1 7.5-2" /></>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="1.5" /><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8" /></>,
  star: <path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9L12 3.5Z" />,
  fit: <><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></>,
  target: <><circle cx="12" cy="12" r="7" /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /></>,
  list: <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />,
  grid: <><rect x="3" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>,
  pencil: <><path d="M4 20h4L19 9l-4-4L4 16v4Z" /><path d="m13.5 6.5 4 4" /></>,
  review: <><path d="M9 4H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3" /><rect x="9" y="2.5" width="6" height="3.5" rx="1" /><path d="m8.5 13.5 2.5 2.5 4.5-5" /></>,
  ship: <><path d="M3 15h18l-2.5 5h-13L3 15Z" /><path d="M6 15V9h12v6" /><path d="M12 9V3M9 6h6" /></>,
  comment: <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-7l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z" />,
  trash: <><path d="M4 7h16" /><path d="M9 7V4.5h6V7" /><path d="M6 7l1 13h10l1-13" /></>,
  isolate: <><rect x="3" y="3" width="18" height="18" rx="2" strokeDasharray="3 3" /><rect x="8" y="8" width="8" height="8" rx="1" /></>,
  layers: <><path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /></>,
  images: <><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="8.5" cy="10" r="1.5" /><path d="m4 17 5-4.5 3.5 3L16 12l4 4" /></>,
  boxes: <><rect x="3" y="4" width="18" height="16" rx="2" /><rect x="6.5" y="7.5" width="6" height="5" rx="1" /><rect x="13" y="13" width="5" height="4" rx="1" /></>,
  down: <path d="M12 5v14M5 12l7 7 7-7" />,
  swap: <><path d="M7 4v13M4 14l3 3 3-3" /><path d="M17 20V7M14 10l3-3 3 3" /></>,
};

export function Icon({ name, size = 16, className }: { name: keyof typeof PATHS | string; size?: number; className?: string }) {
  return (
    <svg
      className={`icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}

/** The mark: a granum is a stack of discs. Each disc is a revision of your data. */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" fill="none">
      {/* A G drawn as a bounding box, with the cyan handle of the corner being edited. */}
      <path d="M18.5 4.75H4.75v22.5h22.5V15.25H16.5" stroke="currentColor" strokeWidth="3.5" />
      <rect x="24" y="1.5" width="6.5" height="6.5" fill="var(--brand, #22d3ee)" />
    </svg>
  );
}

const VERDICT_TEXT: Record<Verdict, string> = {
  block: "Blockers",
  warn: "Warnings",
  pass: "Passed",
};

export function VerdictBadge({ verdict, label }: { verdict: Verdict; label?: string }) {
  const icon = verdict === "block" ? "block" : verdict === "warn" ? "warn" : "check";
  return (
    <span className={`badge badge-${verdict}`}>
      <Icon name={icon} size={13} />
      {label ?? VERDICT_TEXT[verdict]}
    </span>
  );
}

export const SEVERITY_TEXT: Record<Severity, string> = { block: "Blocker", warn: "Warning", info: "Info" };

export function SeverityLabel({ severity }: { severity: Severity }) {
  const icon = severity === "block" ? "block" : severity === "warn" ? "warn" : "info";
  return (
    <span className={`severity severity-${severity}`}>
      <Icon name={icon} size={14} />
      {SEVERITY_TEXT[severity]}
    </span>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      {children && <div className="empty-state-body">{children}</div>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, back, context }: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
  /** Where this page sits, shown above the title (the project, or the run). */
  context?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        {context && !back && <span className="page-context">{context}</span>}
        {back && (
          <a className="back-link" href={back.href}>
            <Icon name="back" size={14} />
            {back.label}
          </a>
        )}
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Progress({ done, total }: { done: number; total: number }) {
  const fraction = total > 0 ? Math.min(1, done / total) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <div className={`progress-fill${total === 0 ? " indeterminate" : ""}`} style={{ width: total ? `${fraction * 100}%` : undefined }} />
    </div>
  );
}

export const formatNumber = (value: number): string => value.toLocaleString("en-US");

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

export function formatWhen(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value.includes("T") && !/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? `${value}Z` : value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace("T", " ");
  const seconds = (Date.now() - date.getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  if (seconds < 86400 * 7) return `${Math.round(seconds / 86400)} d ago`;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function plural(count: number, word: string, many = `${word}s`): string {
  return `${formatNumber(count)} ${count === 1 ? word : many}`;
}

/** The last path segment, for showing a long URL where space is short. */
export function tail(url: string, segments = 1): string {
  return url.split("/").filter(Boolean).slice(-segments).join("/");
}

/** A term with its definition on hover (a native tooltip, so it never interrupts reading). */
export function Term({ term, children }: { term: keyof typeof GLOSSARY; children: ReactNode }) {
  return <span title={GLOSSARY[term]}>{children}</span>;
}

/** A row of headline numbers in one bordered strip. */
export function StatStrip({ items }: { items: { label: string; value: ReactNode; detail?: ReactNode }[] }) {
  return (
    <dl className="stat-strip">
      {items.map((item) => (
        <div key={item.label} className="stat">
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.detail !== undefined && <span className="stat-detail">{item.detail}</span>}
        </div>
      ))}
    </dl>
  );
}

const RUN_STATUS: Record<string, { label: string; tone: string }> = {
  running: { label: "Running", tone: "run" },
  finished: { label: "Finished", tone: "pass" },
  cancelled: { label: "Cancelled", tone: "muted" },
  failed: { label: "Failed", tone: "block" },
  interrupted: { label: "Interrupted", tone: "warn" },
};

export function RunStatus({ status, epochs, total }: { status?: string; epochs?: number; total?: unknown }) {
  const known = RUN_STATUS[status ?? ""] ?? { label: status ?? "Unknown", tone: "muted" };
  return (
    <span className={`status status-${known.tone}`}>
      <span className="status-mark" aria-hidden="true" />
      {known.label}
      {status === "running" && epochs !== undefined && <span className="status-progress">{epochs}/{String(total ?? "?")}</span>}
    </span>
  );
}

/** A small "?" that explains something in a sentence or two. */
export function HelpTip({ children, label = "What does this mean?" }: { children: ReactNode; label?: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className="help-tip" onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="help-tip-button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen(!open)}
        onMouseEnter={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        ?
      </button>
      {open && <span role="tooltip" id={id} className="term-tip visible">{children}</span>}
    </span>
  );
}

/** Thumbnails spread through one dataset version, edge to edge. */
export function ImageStrip({ url, project, dataset, count = 12, height = 96, onOpen }: {
  url: string;
  project: string;
  dataset: string;
  count?: number;
  height?: number;
  onOpen?: () => void;
}) {
  const [images, setImages] = useState<string[] | null>(null);
  useEffect(() => {
    let alive = true;
    api.tableSample(url, count)
      .then((result) => alive && setImages(result.images.map((i) => i.image)))
      .catch(() => alive && setImages([]));
    return () => {
      alive = false;
    };
  }, [url, count]);
  return (
    <div className={`image-strip${onOpen ? " clickable" : ""}`} style={{ height }} onClick={onOpen} aria-hidden="true">
      {(images ?? Array.from({ length: count }, () => "")).map((image, i) => (
        <span key={i} className="image-strip-cell">
          {image && <img loading="lazy" src={api.mediaUrl(image, 256, project, dataset)} alt="" />}
        </span>
      ))}
    </div>
  );
}
