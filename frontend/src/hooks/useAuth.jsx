import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { setUnauthorizedHandler, tokenStore } from "../services/api";
import { authService } from "../services/authService";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  // Any 401 from the API (expired token) logs the user out.
  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  // On page load, restore the session from the saved token.
  useEffect(() => {
    if (!tokenStore.get()) return;
    authService
      .me()
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, []);

  const handleAuth = (response) => {
    tokenStore.set(response.access_token);
    setUser(response.user);
    return response.user;
  };

  const value = useMemo(
    () => ({
      user,
      loading,
      login: async (email, password) => handleAuth(await authService.login(email, password)),
      register: async (email, password, fullName) => handleAuth(await authService.register(email, password, fullName)),
      logout,
    }),
    [user, loading, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
