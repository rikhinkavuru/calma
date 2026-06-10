"use client";

const ITEMS = [
  ["251 deterministic checks", true],
  ["0 model opinions in any verdict", true],
  ["15 metric recipes", false],
  ["python · r · julia · c++ · rust", false],
  ["verified sandbox, proven by self-test", false],
  ["+14,698% → −32.4% — caught by re-execution", true],
  ["content-addressed verdict cache", false],
  ["in-toto / cyclonedx attestations", false],
] as const;

export function Marquee() {
  const row = (
    <>
      {ITEMS.map(([t, hot], i) => (
        <span className="marquee__item" key={i}>
          {hot ? <em>{t}</em> : t}
          <span className="marquee__sep">/</span>
        </span>
      ))}
    </>
  );
  return (
    <div className="marquee" aria-hidden="true">
      <div className="marquee__track">
        {row}
        {row}
      </div>
    </div>
  );
}
