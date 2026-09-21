/** The licence of this computer: what it allows, until when, and where a new key goes. */

import { useState } from "react";
import { api } from "../api/client";
import type { LicenceStatus } from "../api/types";
import { Icon, PageHeader, formatNumber } from "../components/ui";
import { useStore } from "../store/store";

const STATE_LABEL: Record<LicenceStatus["state"], string> = {
  active: "Active",
  unrestricted: "Unrestricted",
  missing: "No licence",
  invalid: "Invalid key",
  wrong_machine: "Other computer",
  clock: "Clock turned back",
  expired: "Ended",
  lease_expired: "Renewal needed",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "No end date";
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function LicencePage() {
  const licence = useStore((s) => s.licence);
  const refreshLicence = useStore((s) => s.refreshLicence);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [manual, setManual] = useState(false);

  if (!licence) {
    return <div className="page"><PageHeader title="Licence" /><p className="muted"><span className="spinner" /> Loading</p></div>;
  }

  const hasKey = Boolean(licence.lid);
  const full = licence.mode === "full";
  const needsSignIn = !full || !hasKey;
  // With a licence server, signing in is the way in; a key by hand is for offline computers.
  const signIn = licence.server && needsSignIn;
  const showEntry = (!signIn || manual) && (!hasKey || replacing || licence.state === "invalid" || licence.state === "wrong_machine" || manual);

  const activate = async () => {
    setBusy(true);
    setError(null);
    try {
      useStore.setState({ licence: await api.installLicence(key.trim()) });
      setKey("");
      setReplacing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      // Online keys also free this computer on the server, so the plan can move.
      useStore.setState({ licence: licence.kind === "online" && licence.server ? await api.licenceSignOut() : await api.removeLicence() });
      setConfirmRemove(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const renew = async () => {
    setBusy(true);
    setError(null);
    try {
      useStore.setState({ licence: await api.licenceRenew() });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      void refreshLicence();
    } finally {
      setBusy(false);
    }
  };

  const copyMachine = async () => {
    try {
      await navigator.clipboard.writeText(licence.machine);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* the id stays selectable */
    }
  };

  const projects = licence.max_projects == null
    ? `${formatNumber(licence.projects_used)} · no limit`
    : `${formatNumber(licence.projects_used)} of ${formatNumber(licence.max_projects)}`;

  return (
    <div className="page page-narrow licence-page">
      <PageHeader title="Licence" subtitle={licence.email ?? "This computer"} />

      <section className={`licence-card${full ? "" : " limited"}`}>
        <header className="licence-card-head">
          <span className={`licence-state ${full ? "ok" : "off"}`}>
            <span className="status-mark" aria-hidden="true" />
            {STATE_LABEL[licence.state]}
          </span>
          <h2>{hasKey ? licence.plan || "Granum" : "Read-only"}</h2>
          {hasKey && licence.customer && licence.customer !== licence.email && <span className="muted small">{licence.customer}</span>}
          <span className="spacer" />
          {licence.days_left != null && full && <span className="licence-days tabular">{formatNumber(Math.floor(licence.days_left))} days left</span>}
        </header>

        {!full && licence.reason && (
          <div className="licence-reason" role="alert">
            <Icon name="warn" size={16} />
            <div>
              <strong>{licence.reason}</strong>
              <span className="muted small">Projects stay open for viewing and export. Creating, editing and training are paused.</span>
            </div>
          </div>
        )}

        {hasKey && (
          <dl className="licence-facts">
            <div><dt>Plan ends</dt><dd>{formatDate(licence.expires)}</dd></div>
            <div><dt>Projects</dt><dd className="tabular">{projects}</dd></div>
            <div><dt>Machines</dt><dd className="tabular">{licence.machines ?? 1}</dd></div>
            <div>
              <dt>Offline use</dt>
              <dd className="tabular">
                {licence.kind === "online"
                  ? `${licence.offline_days_left ?? 0} of ${licence.lease_days} days left`
                  : "Not needed"}
              </dd>
            </div>
            <div><dt>Licence ID</dt><dd className="mono">{licence.lid}</dd></div>
            <div><dt>Issued</dt><dd>{formatDate(licence.issued)}</dd></div>
          </dl>
        )}
      </section>

      {signIn && <SignIn />}

      <section className="licence-section">
        <h3>This computer</h3>
        <div className="licence-machine">
          <code>{licence.machine}</code>
          <button className="button small" onClick={() => void copyMachine()}>
            <Icon name={copied ? "check" : "copy"} size={13} />{copied ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="faint small">Licence keys are issued for this machine ID and work on this computer only.</p>
      </section>

      <section className="licence-section">
        <div className="licence-section-head">
          <h3>Licence key</h3>
          <span className="spacer" />
          {hasKey && !showEntry && (
            <>
              {licence.kind === "online" && licence.server && (
                <button className="button subtle small" disabled={busy} onClick={() => void renew()}>Renew now</button>
              )}
              {!(licence.kind === "online" && licence.server) && (
                <button className="button subtle small" onClick={() => setReplacing(true)}>Replace key</button>
              )}
              {confirmRemove ? (
                <span className="licence-confirm">
                  <span className="small">
                    {licence.kind === "online" && licence.server ? "Sign out? This computer's place on the plan is freed." : "Remove the key? Granum becomes read-only."}
                  </span>
                  <button className="button small danger-button" disabled={busy} onClick={() => void remove()}>
                    {licence.kind === "online" && licence.server ? "Sign out" : "Remove"}
                  </button>
                  <button className="button subtle small" onClick={() => setConfirmRemove(false)}>Keep</button>
                </span>
              ) : (
                <button className="button subtle small" onClick={() => setConfirmRemove(true)}>
                  {licence.kind === "online" && licence.server ? "Sign out" : "Remove"}
                </button>
              )}
            </>
          )}
          {signIn && !manual && (
            <button className="button subtle small" onClick={() => setManual(true)}>Enter a key instead</button>
          )}
        </div>
        {showEntry ? (
          <div className="licence-entry">
            <textarea
              className="licence-key-input mono"
              rows={4}
              spellCheck={false}
              placeholder="GRN1.…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              aria-label="Licence key"
            />
            <div className="licence-entry-foot">
              {error && <span className="form-error">{error}</span>}
              <span className="spacer" />
              {replacing && <button className="button subtle" onClick={() => { setReplacing(false); setError(null); }}>Cancel</button>}
              <button className="button primary" disabled={busy || key.trim().length < 20} onClick={() => void activate()}>
                {busy ? "Activating" : "Activate"}
              </button>
            </div>
          </div>
        ) : signIn ? (
          <p className="muted small">For computers without internet, a key can be entered by hand.</p>
        ) : (
          <p className="muted small">
            A key is installed{licence.kind === "online" ? " and renews automatically while Granum runs online" : ""}.
            {error && <span className="form-error"> {error}</span>}
          </p>
        )}
        {licence.server_message && <p className="form-error small">{licence.server_message}</p>}
      </section>
    </div>
  );
}

/** Email, then the emailed code: the server answers with this computer's plan or a free trial. */
function SignIn() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const sent = await api.licenceCode(email.trim());
      setSentTo(email.trim());
      setDevCode(sent.dev_code ?? null);
      setCode("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const activate = async () => {
    setBusy(true);
    setError(null);
    try {
      useStore.setState({ licence: await api.licenceActivate(sentTo ?? email.trim(), code.trim()) });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="licence-signin">
      <div className="licence-signin-head">
        <h3>Start a free trial or activate your plan</h3>
        <p className="muted small">Use the email you downloaded Granum with. A new email starts a 7-day free trial; a purchased plan activates on this computer.</p>
      </div>
      {sentTo === null ? (
        <form className="licence-signin-row" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <input type="email" className="licence-email" placeholder="you@company.com" value={email} autoFocus
            onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
          <button type="submit" className="button primary" disabled={busy || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())}>
            {busy ? "Sending" : "Send code"}
          </button>
        </form>
      ) : (
        <>
          <p className="small">A 6-digit code was sent to <strong>{sentTo}</strong>. It expires in 10 minutes.</p>
          <form className="licence-signin-row" onSubmit={(e) => { e.preventDefault(); void activate(); }}>
            <input className="licence-code mono" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000"
              value={code} autoFocus onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} aria-label="Code" />
            <button type="submit" className="button primary" disabled={busy || code.length !== 6}>{busy ? "Activating" : "Activate"}</button>
            <span className="spacer" />
            <button type="button" className="button subtle small" disabled={busy} onClick={() => void send()}>Send again</button>
            <button type="button" className="button subtle small" onClick={() => { setSentTo(null); setError(null); }}>Change email</button>
          </form>
          {devCode && <p className="faint small">Development server: the code is <span className="mono">{devCode}</span></p>}
        </>
      )}
      {error && <p className="form-error">{error}</p>}
    </section>
  );
}
