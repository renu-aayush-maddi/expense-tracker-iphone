import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { isAdmin } from "../admin/adminService";
import { useAuth } from "../hooks/useAuth";

const LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/transactions", label: "Transactions" },
  { to: "/add-expense", label: "Add expense" },
  { to: "/import", label: "Import" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/dashboard" className="brand" onClick={() => setMenuOpen(false)}>
            <span className="brand-mark">₹</span> Expense Tracker
          </NavLink>
          <button
            type="button"
            className="menu-toggle"
            aria-label="Toggle menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            ☰
          </button>
          <nav className={`nav ${menuOpen ? "nav-open" : ""}`}>
            {LINKS.map((link) => (
              <NavLink key={link.to} to={link.to} className="nav-link" onClick={() => setMenuOpen(false)}>
                {link.label}
              </NavLink>
            ))}
            {isAdmin(user) && (
              <NavLink to="/admin" className="nav-link nav-admin" onClick={() => setMenuOpen(false)}>
                Admin
              </NavLink>
            )}
            <div className="nav-user">
              <span className="muted small" title={user?.email}>
                {user?.full_name || user?.email}
              </span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={logout}>
                Log out
              </button>
            </div>
          </nav>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
