import { Navigate, Outlet } from "react-router-dom";
import Loading from "../components/Loading";
import ChangePasswordPage from "../pages/ChangePasswordPage";
import { useAuth } from "../hooks/useAuth";
import { isAdmin } from "./adminService";

/** UI guard only: every admin API call is authorized again on the server. */
export default function AdminRoute() {
  const { user, loading } = useAuth();
  if (loading) return <Loading full />;
  if (!user) return <Navigate to="/login" replace state={{ from: "/admin" }} />;
  if (user.must_change_password) return <ChangePasswordPage forced />;
  if (!isAdmin(user)) return <Navigate to="/dashboard" replace />;
  return <Outlet />;
}
