"use client";

import { useState, useEffect, useCallback } from "react";
import {
  auth,
  isFirebaseConfigured,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  googleProvider,
  signOut,
  User,
} from "@/lib/firebase";

/**
 * Custom hook for Firebase Auth.
 *
 * When Firebase is NOT configured (no API key in .env.local), the hook
 * returns a fake "always authenticated" state so the app runs in open-access
 * mode without crashing.
 */
export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // If Firebase isn't configured, skip auth — treat as always logged in
    if (!isFirebaseConfigured || !auth) {
      setUser({ email: "guest@local" } as User);
      setLoading(false);
      return;
    }

    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      setUser(firebaseUser);
      setLoading(false);
    });
    return unsubscribe;
  }, []);

  const loginWithEmail = useCallback(
    async (email: string, password: string) => {
      if (!auth) return;
      setError(null);
      try {
        const result = await signInWithEmailAndPassword(auth, email, password);
        setUser(result.user);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Login failed";
        setError(
          msg.replace("Firebase: ", "").replace(/\(auth\/.*?\)/, "").trim()
        );
        throw err;
      }
    },
    []
  );

  const signupWithEmail = useCallback(
    async (email: string, password: string) => {
      if (!auth) return;
      setError(null);
      try {
        const result = await createUserWithEmailAndPassword(auth, email, password);
        setUser(result.user);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Signup failed";
        setError(
          msg.replace("Firebase: ", "").replace(/\(auth\/.*?\)/, "").trim()
        );
        throw err;
      }
    },
    []
  );

  const loginWithGoogle = useCallback(async () => {
    if (!auth || !googleProvider) return;
    setError(null);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      setUser(result.user);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Google login failed";
      setError(
        msg.replace("Firebase: ", "").replace(/\(auth\/.*?\)/, "").trim()
      );
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    if (!auth) return;
    await signOut(auth);
    setUser(null);
  }, []);

  return {
    user,
    loading,
    error,
    isConfigured: isFirebaseConfigured,
    loginWithEmail,
    signupWithEmail,
    loginWithGoogle,
    logout,
  };
}
