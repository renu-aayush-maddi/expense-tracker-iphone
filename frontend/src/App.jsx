import { Navigate, Route, Routes } from "react-router-dom";
import { lazy, Suspense } from "react";
import AdminRoute from "./admin/AdminRoute";
import Loading from "./components/Loading";
import Layout from "./components/Layout";
import { ProtectedRoute, PublicOnlyRoute } from "./components/ProtectedRoute";
import AddExpensePage from "./pages/AddExpensePage";
import DashboardPage from "./pages/DashboardPage";
import ImportPage from "./pages/ImportPage";
import LoginPage from "./pages/LoginPage";
import NotFoundPage from "./pages/NotFoundPage";
import RegisterPage from "./pages/RegisterPage";
import ReviewImportPage from "./pages/ReviewImportPage";
import SettingsPage from "./pages/SettingsPage";
import TransactionDetailPage from "./pages/TransactionDetailPage";
import TransactionsPage from "./pages/TransactionsPage";

// The admin console is a separate download: normal users never load its code.
const AdminLayout = lazy(() => import("./admin/AdminLayout"));
const AdminDashboard = lazy(() => import("./admin/pages/AdminDashboard"));
const AdminUsers = lazy(() => import("./admin/pages/AdminUsers"));
const AdminUserDetail = lazy(() => import("./admin/pages/AdminUserDetail"));
const AdminAdmins = lazy(() => import("./admin/pages/AdminAdmins"));
const AdminTransactions = lazy(() => import("./admin/pages/AdminTransactions"));
const AdminAuditLogs = lazy(() => import("./admin/pages/AdminAuditLogs"));
const AdminSecurity = lazy(() => import("./admin/pages/AdminSecurity"));
const AdminSessions = lazy(() => import("./admin/pages/AdminSessions"));
const AdminIpAddresses = lazy(() => import("./admin/pages/AdminIpAddresses"));
const AdminSystem = lazy(() => import("./admin/pages/AdminSystem"));
const AdminReports = lazy(() => import("./admin/pages/AdminReports"));

export default function App() {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Route>

      {/* Admin area: UI guard only – every /api/admin call is authorized on the server. */}
      <Route element={<AdminRoute />}>
        <Route path="/admin" element={<Suspense fallback={<Loading full />}><AdminLayout /></Suspense>}>
          <Route index element={<AdminDashboard />} />
          <Route path="users" element={<AdminUsers />} />
          <Route path="users/:id" element={<AdminUserDetail />} />
          <Route path="admins" element={<AdminAdmins />} />
          <Route path="transactions" element={<AdminTransactions />} />
          <Route path="audit-logs" element={<AdminAuditLogs />} />
          <Route path="security" element={<AdminSecurity />} />
          <Route path="sessions" element={<AdminSessions />} />
          <Route path="ip-addresses" element={<AdminIpAddresses />} />
          <Route path="system" element={<AdminSystem />} />
          <Route path="reports" element={<AdminReports />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/transactions" element={<TransactionsPage />} />
          <Route path="/transactions/:id" element={<TransactionDetailPage />} />
          <Route path="/add-expense" element={<AddExpensePage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/imports/:id" element={<ReviewImportPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
