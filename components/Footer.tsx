"use client";

export function Footer() {
  return (
    <footer className="foot wrap">
      <div className="foot-grid">
        <div className="fm">
          calma<span className="dot">.</span>
        </div>
        <div className="fr">
          Verification by re-execution
          <br />
          The producer is never the verifier
          <br />
          <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
            GitHub
          </a>
          {" · "}
          <a
            href="https://github.com/rikhinkavuru/calma/blob/main/README.md"
            target="_blank"
            rel="noreferrer"
          >
            Docs
          </a>
          {" · "}
          <a
            href="https://github.com/rikhinkavuru/calma/blob/main/LICENSE"
            target="_blank"
            rel="noreferrer"
          >
            MIT
          </a>
          {" · "}© 2026
        </div>
      </div>
    </footer>
  );
}
