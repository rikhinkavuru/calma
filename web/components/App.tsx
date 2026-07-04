// Landing — a SERVER component. Each section renders to HTML on the server; only the genuinely
// interactive pieces hydrate as small client islands (the nav, the scroll-progress bar, the FAQ
// accordion, the hero's WebGL backdrop + lazy video, and the per-section scroll reveals).
//
// Previously this whole tree was one "use client" component: the entire page shipped as JavaScript and
// hydrated as a unit, which is exactly why content appeared one piece at a time. Server-first rendering
// puts the markup on screen immediately and layers the islands on top. (Reveal handles reduced-motion
// itself now, so the MotionConfig wrapper that required a client boundary here is gone.)
import { SiteNav } from "./SiteNav";
import { Hero } from "./Hero";
import { BpProgress } from "./home/BpProgress";
import { BpFlow } from "./home/BpFlow";
import { BpMoats } from "./home/BpMoats";
import { BpFaq } from "./home/BpFaq";
import { BpFooter } from "./home/BpFooter";

// Landing: hero → convergence (flow) → features (moats) → FAQ → footer.
export default function App() {
  return (
    <>
      <BpProgress />
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main>
        <Hero />
        <BpFlow />
        <BpMoats />
        <section className="flowsec faqsec">
          <div className="wrap">
            <BpFaq />
          </div>
        </section>
      </main>

      <BpFooter />
    </>
  );
}
