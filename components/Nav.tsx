"use client";

export function Nav({ onRequest }: { onRequest: () => void }) {
  return (
    <div className="navwrap wrap">
      <nav className="nav">
        <a href="#top" className="brand" aria-label="calma — home">
          calma<span className="dot">.</span>
        </a>
        <ul>
          <li><a href="#bench">Bench</a></li>
          <li><a href="#method">Method</a></li>
          <li><a href="#verdicts">Verdicts</a></li>
          <li><a href="#evidence">Evidence</a></li>
          <li><a href="#get">Get it</a></li>
        </ul>
        <div className="nav__right">
          <button className="explore" onClick={onRequest}>
            Request verification
            <span className="nub" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            </span>
          </button>
        </div>
      </nav>
    </div>
  );
}
