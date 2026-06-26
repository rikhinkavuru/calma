import Link from "next/link";
import { CONTACT_EMAIL, FOUNDER, GITHUB_URL } from "../contact";

export function BpFooter() {
  return (
    <footer className="bp-footer">
      <div className="bp-footer__in">
        <div>
          <div className="bp-footer__lead">Verification infrastructure for AI results.</div>
          <p className="bp-footer__sub">One deterministic engine. Pure Python stdlib, fully offline, MIT licensed.</p>
        </div>
        <div className="bp-fcol">
          <h5>Product</h5>
          <a href="#flow">How it works</a>
          <a href="#features">Features</a>
          <a href="#faq">FAQ</a>
          <Link href="/install">Docs</Link>
        </div>
        <div className="bp-fcol">
          <h5>Resources</h5>
          <Link href="/recipes">Recipes</Link>
          <Link href="/registry">Registry</Link>
          <Link href="/lab">The lab</Link>
        </div>
        <div className="bp-fcol">
          <h5>Engine</h5>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
          <a href={`${GITHUB_URL}/blob/main/CHANGELOG.md`} target="_blank" rel="noreferrer">Changelog</a>
          <a href={`${GITHUB_URL}/blob/main/README.md`} target="_blank" rel="noreferrer">README</a>
        </div>
        <div className="bp-fcol">
          <h5>Connect</h5>
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub ↗</a>
        </div>
      </div>

      <div className="bp-footer__copy">© 2026 Calma · run by {FOUNDER} · catch your own wrong number first</div>

      <div className="bp-footer__mark">
        <div><img src="/img/calma-lotus.png" alt="Calma" /></div>
      </div>
      <div className="bp-footer__wm" aria-hidden="true">calma.</div>
    </footer>
  );
}
