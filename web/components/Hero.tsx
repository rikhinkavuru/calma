// Hero — a SERVER component. The headline, lead, CTAs, and video poster are server-rendered HTML, so
// they paint together on first load with no hydration wait and no staggered reveal. Only the two
// genuinely interactive pieces are client islands: the WebGL backdrop and the lazy video.
import { HeroBackdrop } from "./hero/HeroBackdrop";
import { HeroVideo } from "./hero/HeroVideo";

export function Hero() {
  return (
    <section className="hero" id="top">
      {/* atmosphere — CSS only, server-rendered */}
      <div className="atmo" aria-hidden="true">
        <i className="glow-blue" />
        <i className="glow-teal" />
        <i className="glow-amber" />
      </div>

      {/* gradient blinds (client island) + grain overlay */}
      <div className="hero__blinds" aria-hidden="true">
        <HeroBackdrop />
        <div className="hero__grain" />
      </div>

      <div className="wrap hero__inner hero__inner--center">
        <div>
          <h1 className="h1">AI did the work. Calma checks it.</h1>
        </div>

        <div>
          <p className="lead hero__lead">
            Everyone else reads the diff or trusts the score. <b>Calma re-runs the work and
            recomputes the number</b> — from the raw outputs, never the one your agent reported —
            and blocks the wrong one before it ships.
          </p>
        </div>

        <div>
          <div className="hero__cta">
            {/* primary CTA → the verify flow inside the WorkOS-gated dashboard. Anonymous users hit the
                sign-in card first; the dashboard proxies submissions to the verification API server-side. */}
            <a className="btn-primary" href="/dashboard/verify">
              Verify a repo <span className="arrow" aria-hidden="true">→</span>
            </a>
            <a className="btn-ghost" href="/install">Install the CLI</a>
          </div>
        </div>

        <div className="hero__fill">
          <div className="hero__demo">
            <HeroVideo />
          </div>
        </div>
      </div>
    </section>
  );
}
