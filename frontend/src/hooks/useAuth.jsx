import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { setUnauthorizedHandler, tokenStore } from "../services/api";
import { authService } from "../services/authService";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));

  // Local logout (used when the server already rejected the session).
  const clearSession = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  // Real logout: end the session on the server too, so the token can't be reused.
  const logout = useCallback(async () => {
    try {
      if (tokenStore.get()) await authService.logout();
    } catch {
      // already invalid – nothing to end on the server
    }
    clearSession();
  }, [clearSession]);

  // Any 401 from the API (expired token) logs the user out.
  useEffect(() => {
    setUnauthorizedHandler(clearSession);
  }, [clearSession]);

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
      changePassword: async (currentPassword, newPassword) => {
        await authService.changePassword(currentPassword, newPassword);
        setUser(await authService.me());
      },
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
