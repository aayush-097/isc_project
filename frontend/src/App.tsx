import { useEffect, useState } from "react";

import CaseLibrary from "./pages/CaseLibrary";
import UploadPage from "./pages/UploadPage";
import VideoDetails from "./pages/VideoDetails";
import { getHealth } from "./lib/api";

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

  useEffect(() => {
    let active = true;
    getHealth()
      .then(() => active && setHealth("online"))
      .catch(() => active && setHealth("error"));
    return () => {
      active = false;
    };
  }, []);

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
          <a href="/login">Log in</a>
          <a className="button button-small" href="/register">Create account</a>
        </div>
      </header>

      <main>
        <div className="prototype-banner">
          <span className="status-dot" />
          Local development prototype <span className="banner-divider">/</span>
          Uploads are unauthenticated; do not expose this service to an untrusted network.
        </div>
        {page === "cases" && <CaseLibrary />}
        {page === "upload" && <UploadPage />}
        {page === "login" && <AuthPage mode="login" />}
        {page === "register" && <AuthPage mode="register" />}
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

function AuthPage({ mode }: { mode: "login" | "register" }) {
  const isLogin = mode === "login";
  return (
    <section className="content content-narrow">
      <PageIntro
        eyebrow="Account"
        title={isLogin ? "Welcome back" : "Create your account"}
        description={isLogin
          ? "Sign-in will be enabled when the secure session flow is implemented."
          : "Account creation will be enabled when authentication is implemented."}
      />
      <div className="form-card">
        <label>Username<input autoComplete="username" disabled placeholder="Your username" /></label>
        <label>Password<input autoComplete={isLogin ? "current-password" : "new-password"} disabled placeholder="At least 12 characters" type="password" /></label>
        <button className="button button-full" type="button" disabled>
          {isLogin ? "Log in" : "Create account"}
        </button>
        <p className="form-note">Authentication is intentionally deferred; no credentials are collected.</p>
        <a className="text-link" href={isLogin ? "/register" : "/login"}>
          {isLogin ? "Need an account? Register" : "Already registered? Log in"}
        </a>
      </div>
    </section>
  );
}

export default App;
