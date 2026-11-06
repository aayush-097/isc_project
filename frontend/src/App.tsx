import { useEffect, useState, type FormEvent } from "react";

import CaseLibrary from "./pages/CaseLibrary";
import UploadPage from "./pages/UploadPage";
import VideoDetails from "./pages/VideoDetails";
import {
  getCurrentUser,
  getHealth,
  login,
  logout,
  register,
  setCsrfToken,
  ApiRequestError,
  type UserResponse,
} from "./lib/api";

type Page = "cases" | "upload" | "login" | "register" | "case";

const currentPage = (): Page => {
  const path = window.location.pathname;
  if (path === "/upload") return "upload";
  if (path === "/login") return "login";
  if (path === "/register") return "register";
  if (path.startsWith("/cases/")) return "case";
  return "cases";
};

function App() {
  const [page] = useState<Page>(currentPage);
  const [health, setHealth] = useState<"loading" | "online" | "error">("loading");
  const [user, setUser] = useState<UserResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    let active = true;
    getHealth()
      .then(() => active && setHealth("online"))
      .catch(() => active && setHealth("error"));
    getCurrentUser()
      .then((currentUser) => {
        if (!active) return;
        setCsrfToken(currentUser.csrf_token);
        setUser(currentUser);
      })
      .catch((error: unknown) => {
        if (active) {
          setCsrfToken("");
          setUser(null);
          if (!(error instanceof ApiRequestError && error.status === 401)) {
            setAuthError(error instanceof Error ? error.message : "Could not check the current session.");
          }
        }
      })
      .finally(() => active && setAuthLoading(false));
    return () => {
      active = false;
    };
  }, []);

  async function handleLogout() {
    setAuthError("");
    try {
      await logout();
      setUser(null);
      window.location.assign("/login");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Could not sign out.");
    }
  }

  function handleAuthenticated(authenticatedUser: UserResponse) {
    setUser(authenticatedUser);
    window.location.assign("/cases");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/cases" aria-label="Face Privacy home">
          <span className="brand-mark">fp</span>
          <span>frame<span className="brand-light">safe</span></span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a className={page === "cases" || page === "case" ? "active" : ""} href="/cases">
            Library
          </a>
          <a className={page === "upload" ? "active" : ""} href="/upload">
            Upload video
          </a>
        </nav>
        <div className="account-nav">
          {authLoading ? (
            <span className="microcopy">Checking account…</span>
          ) : user ? (
            <>
              <span className="microcopy">Signed in as {user.username}</span>
              <button className="button button-small" onClick={() => void handleLogout()} type="button">
                Log out
              </button>
            </>
          ) : (
            <>
              <a href="/login">Log in</a>
              <a className="button button-small" href="/register">Create account</a>
            </>
          )}
        </div>
      </header>

      <main>
        {authError && <p className="message message-error content" role="alert">{authError}</p>}
        <div className="prototype-banner">
          <span className="status-dot" />
          Local development prototype <span className="banner-divider">/</span>
          Original videos are owner-only; shared pages expose validated blurred output.
        </div>
        {page === "cases" && <CaseLibrary authenticated={Boolean(user)} />}
        {page === "upload" && <UploadPage authenticated={Boolean(user)} />}
        {page === "login" && <AuthPage mode="login" onAuthenticated={handleAuthenticated} />}
        {page === "register" && <AuthPage mode="register" onAuthenticated={handleAuthenticated} />}
        {page === "case" && <VideoDetails caseId={window.location.pathname.slice("/cases/".length)} />}
      </main>
      <footer className="footer">
        <span>framesafe <span className="footer-muted">· privacy by design</span></span>
        <span className={`api-status api-${health}`}>
          <span className="status-dot" />
          {health === "loading" && "Checking API"}
          {health === "online" && "API connected"}
          {health === "error" && "API unavailable"}
        </span>
      </footer>
    </div>
  );
}

function PageIntro({ eyebrow, title, description }: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="intro-copy">{description}</p>
    </div>
  );
}

function AuthPage({
  mode,
  onAuthenticated,
}: {
  mode: "login" | "register";
  onAuthenticated: (user: UserResponse) => void;
}) {
  const isLogin = mode === "login";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    const normalizedUsername = username.trim().toLowerCase();
    if (!/^[a-z0-9_.-]{3,64}$/.test(normalizedUsername)) {
      setFormError("Use 3–64 letters, numbers, dots, underscores, or hyphens for your username.");
      return;
    }
    if (password.length < 12 || password.length > 1024) {
      setFormError("Password must be between 12 and 1024 characters.");
      return;
    }
    if (!isLogin && password !== confirmPassword) {
      setFormError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const authenticated = isLogin
        ? await login(normalizedUsername, password)
        : await register(normalizedUsername, password);
      onAuthenticated(authenticated);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="content content-narrow">
      <PageIntro
        eyebrow="Account"
        title={isLogin ? "Welcome back" : "Create your account"}
        description={isLogin
          ? "Sign in to your FrameSafe account."
          : "Create an account with a unique username and a strong password."}
      />
      <form className="form-card" onSubmit={(event) => void handleSubmit(event)}>
        <label htmlFor="auth-username">
          Username
          <input
            id="auth-username"
            autoComplete="username"
            maxLength={64}
            minLength={3}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Your username"
            required
            value={username}
          />
        </label>
        <label htmlFor="auth-password">
          Password
          <input
            id="auth-password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            maxLength={1024}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="At least 12 characters"
            required
            type="password"
            value={password}
          />
        </label>
        {!isLogin && (
          <label htmlFor="auth-confirm-password">
            Confirm password
            <input
              id="auth-confirm-password"
              autoComplete="new-password"
              maxLength={1024}
              minLength={12}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Re-enter your password"
              required
              type="password"
              value={confirmPassword}
            />
          </label>
        )}
        {formError && <p className="message message-error" role="alert">{formError}</p>}
        <button className="button button-full" type="submit" disabled={submitting}>
          {submitting ? "Please wait…" : isLogin ? "Log in" : "Create account"}
        </button>
        <p className="form-note">Passwords are stored as Argon2 hashes and never returned by the API.</p>
        <a className="text-link" href={isLogin ? "/register" : "/login"}>
          {isLogin ? "Need an account? Register" : "Already registered? Log in"}
        </a>
      </form>
    </section>
  );
}

export default App;
