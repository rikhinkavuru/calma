import { ImageResponse } from "next/og";

export const alt =
  "Calma — AI did the work. Calma checks it. A guardrail for AI-generated results.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/* Purely typographic card on the warm-black void, matching the site's
   :root tokens (void #0d0b08, cream #e9ddc4, amber #e89a5d). Rendered
   statically at build — no external images or font fetches. */
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          backgroundColor: "#0d0b08",
          color: "#e9ddc4",
          padding: "64px 80px 56px",
        }}
      >
        {/* wordmark row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div
            style={{
              display: "flex",
              fontSize: 30,
              letterSpacing: "0.5em",
              color: "#e9ddc4",
            }}
          >
            CALMA
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 17,
              letterSpacing: "0.3em",
              color: "#e89a5d",
            }}
          >
            VERIFICATION
          </div>
        </div>

        {/* headline */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 36,
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              fontSize: 88,
              fontWeight: 800,
              lineHeight: 1.08,
              letterSpacing: "-0.02em",
            }}
          >
            <div style={{ display: "flex" }}>AI did the work.</div>
            <div style={{ display: "flex" }}>
              <span style={{ color: "#e89a5d" }}>Calma checks it.</span>
            </div>
          </div>

          {/* amber accent rule */}
          <div
            style={{
              display: "flex",
              width: 168,
              height: 6,
              backgroundColor: "#e89a5d",
            }}
          />

          <div
            style={{
              display: "flex",
              fontSize: 30,
              color: "rgba(233, 221, 196, 0.7)",
            }}
          >
            A guardrail for the numbers your AI produces
          </div>
        </div>

        {/* baseline */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            borderTop: "1px solid rgba(233, 221, 196, 0.16)",
            paddingTop: 22,
            fontSize: 16,
            letterSpacing: "0.22em",
            color: "rgba(233, 221, 196, 0.35)",
          }}
        >
          <div style={{ display: "flex" }}>RE-EXECUTED. RECOMPUTED. SEALED.</div>
          <div style={{ display: "flex" }}>CALMA1.VERCEL.APP</div>
        </div>
      </div>
    ),
    { ...size }
  );
}
