import { Suspense, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import Loading from "../components/Loading";
import { useAuth } from "../hooks/useAuth";
import { can, PERMS, ROLE_LABELS } from "./adminService";
import { ToastProvider } from "./components/Toast";

const NAV = [
  { section: "Overview" },
  { to: "/admin", label: "Dashboard", perm: PERMS.dashboard, end: true },
  { to: "/admin/reports", label: "Reports", perm: PERMS.reports },
  { section: "People" },
  { to: "/admin/users", label: "Users", perm: PERMS.usersView, end: true },
  { to: "/admin/users?status=blocked", label: "Blocked users", perm: PERMS.usersView, match: "status=blocked" },
  { to: "/admin/admins", label: "Admins", perm: PERMS.admins },
  { section: "Data" },
  { to: "/admin/transactions", label: "Transactions", perm: PERMS.txView },
  { section: "Security" },
  { to: "/admin/security", label: "Login & security", perm: PERMS.securityView },
  { to: "/admin/sessions", label: "Sessions", perm: PERMS.securityView },
  { to: "/admin/ip-addresses", label: "IP addresses", perm: PERMS.securityView },
  { to: "/admin/audit-logs", label: "Audit logs", perm: PERMS.audit },
  { section: "Platform" },
  { to: "/admin/system", label: "System health", perm: PERMS.system },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { search } = useLocation();
  const items = NAV.filter((item, index) => {
    if (item.section) {
      // keep a section header only if something under it is visible
      const next = NAV.slice(index + 1);
      const end = next.findIndex((i) => i.section);
      return (end === -1 ? next : next.slice(0, end)).some((i) => can(user, i.perm));
    }
    return can(user, item.perm);
  });

  return (
    <ToastProvider>
      <div className="admin-shell">
        <aside className={`admin-sidebar ${open ? "is-open" : ""}`}>
          <div className="admin-brand">
            <span className="brand-mark">₹</span>
            <div>
              <strong>Expense Tracker</strong>
              <div className="muted small">Admin console</div>
            </div>
          </div>
          <nav className="admin-nav" onClick={() => setOpen(false)}>
            {items.map((item) =>
              item.section ? (
                <div key={item.section} className="admin-nav-section">
                  {item.section}
                </div>
              ) : (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => {
                    const queryMatch = item.match ? search.includes(item.match) : true;
                    const plainUsers = item.to === "/admin/users" && search.includes("status=blocked");
                    return `admin-nav-link ${isActive && queryMatch && !plainUsers ? "active" : ""}`;
                  }}
                >
                  {item.label}
                </NavLink>
              ),
            )}
          </nav>
          <div className="admin-sidebar-footer">
            <div className="small">
              <div className="truncate" title={user.email}>{user.email}</div>
              <div className="muted">{ROLE_LABELS[user.role]}</div>
            </div>
            <Link to="/dashboard" className="btn btn-secondary btn-sm">
              ← Back to app
            </Link>
            <button type="button" className="btn btn-ghost btn-sm" onClick={logout}>
              Log out
            </button>
          </div>
        </aside>
        <div className="admin-main">
          <header className="admin-topbar">
            <button type="button" className="menu-toggle admin-menu-toggle" aria-label="Toggle admin menu"
              aria-expanded={open} onClick={() => setOpen((v) => !v)}>
              ☰
            </button>
            <span className="muted small">Signed in as {ROLE_LABELS[user.role]}</span>
          </header>
          <main className="admin-content">
            <Suspense fallback={<Loading />}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
