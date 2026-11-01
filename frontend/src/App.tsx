import { useEffect, useState } from "react";

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
          Academic prototype <span className="banner-divider">/</span>
          Authentication and video processing are not implemented yet.
        </div>
        {page === "cases" && <Library />}
        {page === "upload" && <Upload />}
        {page === "login" && <AuthPage mode="login" />}
        {page === "register" && <AuthPage mode="register" />}
        {page === "case" && <CaseDetails />}
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

function Library() {
  return (
    <section className="content">
      <PageIntro
        eyebrow="Your workspace"
        title="Case library"
        description="Browse protected videos shared with your account, or start a new case."
      />
      <div className="toolbar">
        <div className="filter-tabs" aria-label="Case filters">
          <button className="filter-active" type="button">All cases <span>0</span></button>
          <button type="button" disabled>Yours</button>
        </div>
        <a className="button" href="/upload"><span aria-hidden="true">＋</span> Upload a video</a>
      </div>
      <div className="empty-card">
        <div className="empty-icon" aria-hidden="true">▧</div>
        <h2>Your library is ready</h2>
        <p>Cases will appear here once video uploads and processing are implemented.</p>
        <a className="text-link" href="/upload">Explore the upload page <span aria-hidden="true">→</span></a>
      </div>
      <p className="status-note"><span className="badge badge-neutral">Yours</span> A badge will identify cases you own.</p>
    </section>
  );
}

function Upload() {
  return (
    <section className="content content-narrow">
      <PageIntro
        eyebrow="New case"
        title="Upload a video"
        description="Start a case to create a public, face-blurred copy while preserving protected originals."
      />
      <div className="upload-card">
        <div className="upload-icon" aria-hidden="true">↑</div>
        <h2>Video upload is not available yet</h2>
        <p>The upload flow will be connected after authentication and the video-protection job are implemented.</p>
        <button className="button" type="button" disabled>Choose a video</button>
        <p className="microcopy">Accepted formats and size limits will be shown here.</p>
      </div>
      <a className="text-link back-link" href="/cases">← Back to library</a>
    </section>
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

function CaseDetails() {
  return (
    <section className="content">
      <a className="text-link back-link" href="/cases">← All cases</a>
      <PageIntro
        eyebrow="Case details"
        title="Case preview"
        description="Video playback, integrity status, and owner controls will be connected in a later phase."
      />
      <div className="details-grid">
        <div className="video-placeholder">
          <span className="play-icon" aria-hidden="true">▶</span>
          <span>Public blurred video preview</span>
          <small>Available after processing is implemented</small>
        </div>
        <aside className="details-panel">
          <div className="panel-section">
            <p className="eyebrow">Integrity</p>
            <span className="badge badge-pending">Not verified</span>
            <p className="panel-copy">Manifest verification is not available yet.</p>
          </div>
          <div className="panel-section">
            <p className="eyebrow">Restore faces</p>
            <button className="button button-full" type="button" disabled>Restore original faces</button>
            <p className="panel-copy">Owner checks and restoration are intentionally deferred.</p>
          </div>
        </aside>
      </div>
    </section>
  );
}

export default App;
