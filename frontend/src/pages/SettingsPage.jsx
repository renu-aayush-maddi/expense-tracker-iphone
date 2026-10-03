import { useState } from "react";
import Alert from "../components/Alert";
import Loading from "../components/Loading";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../hooks/useAuth";
import { API_URL } from "../services/api";
import { settingsService } from "../services/settingsService";
import { formatDateTime } from "../utils/format";

const IMPORT_URL = `${API_URL}/api/transactions/import/phonepe`;

function CopyField({ label, value }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      window.prompt("Copy this value:", value);
    }
  };
  return (
    <div className="field">
      <span>{label}</span>
      <div className="copy-field">
        <input type="text" readOnly value={value} onFocus={(e) => e.target.select()} className="mono" />
        <button type="button" className="btn btn-secondary" onClick={copy}>
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function ImportTokens() {
  const tokens = useApi(() => settingsService.listTokens(), []);
  const [name, setName] = useState("iPhone Shortcut");
  const [newToken, setNewToken] = useState(null);
  const [error, setError] = useState("");

  const create = async (event) => {
    event.preventDefault();
    setError("");
    try {
      const created = await settingsService.createToken(name.trim() || "iPhone Shortcut");
      setNewToken(created.token);
      tokens.reload();
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (token) => {
    if (!window.confirm(`Delete "${token.name}"? Any Shortcut using it will stop working.`)) return;
    try {
      await settingsService.deleteToken(token.id);
      tokens.reload();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="card">
      <h2>iPhone Shortcut</h2>
      <p className="muted">
        Your Shortcut needs two values: the import URL and a personal import token. The token can <strong>only</strong>{" "}
        import receipts. It can't read or change your other data.
      </p>

      <CopyField label="Import URL (for “Get Contents of URL”)" value={IMPORT_URL} />

      {error && <Alert type="error">{error}</Alert>}

      {newToken && (
        <Alert type="success" title="Copy your token now. It won't be shown again.">
          <CopyField label="Import token" value={newToken} />
          <p className="small">
            In the Shortcut, set the header <code>Authorization</code> to <code>Bearer {newToken.slice(0, 10)}…</code>{" "}
            (the word <code>Bearer</code>, a space, then the token).
          </p>
        </Alert>
      )}

      <form className="inline-form" onSubmit={create}>
        <label className="field">
          <span>Token name</span>
          <input type="text" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary">
          Create import token
        </button>
      </form>

      {tokens.loading && <Loading />}
      {tokens.data?.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Token</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tokens.data.map((token) => (
              <tr key={token.id}>
                <td>{token.name}</td>
                <td className="mono">{token.token_hint}</td>
                <td className="small">{token.last_used_at ? formatDateTime(token.last_used_at) : "Never"}</td>
                <td className="num">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => remove(token)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function BankAccounts() {
  const accounts = useApi(() => settingsService.listAccounts(), []);
  const [last4, setLast4] = useState("");
  const [bank, setBank] = useState("");
  const [error, setError] = useState("");

  const create = async (event) => {
    event.preventDefault();
    setError("");
    if (!/^\d{4}$/.test(last4)) return setError("Enter exactly 4 digits.");
    if (!bank.trim()) return setError("Enter the bank name.");
    try {
      await settingsService.createAccount(last4, bank.trim());
      setLast4("");
      setBank("");
      accounts.reload();
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (account) => {
    try {
      await settingsService.deleteAccount(account.id);
      accounts.reload();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="card">
      <h2>Bank accounts</h2>
      <p className="muted">
        PhonePe receipts only show “Debited from XXXXXX096929”, not the bank name. Map the last 4 digits to a bank and
        imports will fill in the bank automatically.
      </p>
      {error && <Alert type="error">{error}</Alert>}
      <form className="inline-form" onSubmit={create}>
        <label className="field">
          <span>Last 4 digits</span>
          <input type="text" inputMode="numeric" maxLength={4} placeholder="6929" value={last4} onChange={(e) => setLast4(e.target.value)} />
        </label>
        <label className="field">
          <span>Bank</span>
          <input type="text" maxLength={100} placeholder="Kotak" value={bank} onChange={(e) => setBank(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary">
          Add
        </button>
      </form>
      {accounts.data?.length > 0 && (
        <table className="table">
          <tbody>
            {accounts.data.map((account) => (
              <tr key={account.id}>
                <td className="mono">•••• {account.account_last4}</td>
                <td>{account.bank_name}</td>
                <td className="num">
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => remove(account)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function SettingsPage() {
  const { user, logout } = useAuth();
  return (
    <div className="page page-narrow">
      <div className="page-header">
        <h1>Settings</h1>
      </div>

      <section className="card">
        <h2>Account</h2>
        <dl className="details-grid">
          <div className="detail">
            <dt>Email</dt>
            <dd>{user.email}</dd>
          </div>
          <div className="detail">
            <dt>Name</dt>
            <dd>{user.full_name || "—"}</dd>
          </div>
          <div className="detail">
            <dt>Member since</dt>
            <dd>{formatDateTime(user.created_at)}</dd>
          </div>
        </dl>
        <button type="button" className="btn btn-secondary" onClick={logout}>
          Log out
        </button>
      </section>

      <ImportTokens />
      <BankAccounts />

      <section className="card">
        <h2>How the Shortcut works</h2>
        <ol className="steps">
          <li>In PhonePe, open a completed transaction and tap <strong>Share Receipt</strong>.</li>
          <li>Choose <strong>Phonepay Automation</strong> from the share sheet.</li>
          <li>The Shortcut extracts the text from the image and sends it to the import URL above.</li>
          <li>The server parses it, checks for duplicates and saves it, or asks you to review it here.</li>
        </ol>
        <p className="muted small">Full step-by-step setup is in the project README, under “iPhone Shortcut setup”.</p>
      </section>
    </div>
  );
}
