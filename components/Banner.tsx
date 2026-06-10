"use client";

export function Banner() {
  return (
    <div className="banner" aria-hidden="true">
      <div className="wrap">
        <div className="banner__t">
          ENGINE <b>000</b>
        </div>
        <div className="banner__meta">
          <span>/// re-run · recompute · diff · decide &gt;&gt;&gt;</span>
          <span className="banner__bar">
            <i></i>
            <em></em>
          </span>
        </div>
      </div>
    </div>
  );
}
