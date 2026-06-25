// A tiny, self-contained demo bundle so a first-time user can run a REAL verification in one click —
// no need to author a verify.yaml or build a tar.gz first. It is the e2e-proven `benchmark/cases/win_b`
// fixture (stdlib-only `gen.py` + its `verify.yaml`), gzipped+tarred and base64-embedded so it ships
// with the deployment and needs no filesystem/tar dependency at runtime. The entrypoint regenerates the
// raw return series; Calma re-executes it offline and recomputes total_return (~0.0077) from the output.
export const DEMO_BUNDLE = {
  // sha256 of the raw .tar.gz bytes below (matches the storage-key derivation in submitDemoAction).
  sha256: "129043564bdc5c3bb0733dd0f06d266013fdf8d283479a19c68e769f92bd1821",
  recipeId: "trading.total_return",
  recipeVersion: "1.0.0",
  entrypoint: "gen.py",
  metric: "total_return",
  // the author's claimed number — Calma recomputes it from the raw outputs and confirms it holds.
  claimedValue: 0.0077,
  base64:
    "H4sIAJp0PWoC/+2WUW+bMBCA88yvsHhYoSMUElK6TnndL9hbFSEXDLEKNrJNCKr633c2CU3SbdKkrZM2f4ogvjvfnc9wpiIsbIfZHyUCbpPE3IHLexwly1mcrBZJmkaJkafxMpqhaPYOdFJhASFn/ye0ablQiMsA5XLncBk2+IkUVEjPFR2TboDInkqV8af1V9ER3ylIibI6rzxJSOHfOwjYozXSQ/QBRfsvB4ym39KaID1ztDxae3EcLVcxbPoKXYPkI4oXy2TlGw/pqQfNQEldgNXNqbICNyaR1SffEbyXMH7YOCUXKEOUIYFZRbwkOuR4WGmBFVG0IUZW6EyOklD/8RbRIglQDD8fkpp0+lKQWmEwH+Q68/2QSg6xGqw83zgT4CwK4YG+g4keI3vlVT6agwyWda1V8WgHqYa4bQkrPK8IYNzBPxGgO9/3nZ6qLeKgHOt/I4jqBJMh7A7shdvDhZG+poysXddHWKJyXF8P4cEo7AVVRHil/xn1hwHvvYcrvZSrAMGd1kM2ur3ajKnrmglTM8jt/nSe8J2Z5d9lRwQth3DATf3X+v8tNPuz/h9HcZra/v8ePMP7rxuNe4+eTStwCVNiaDllCmRuZb4P3GDUMaJ6Lp60gpflUZr3hZaELgxftAx87E4c5lwOUpFGG+FO8eM8JaD4xlfP5jkvyKsDLBQtca4kqB+M9fPhMHBbrLZ60tvueLTIed01TE4ZGKFuf2cSnQCutCdaMS7INH80V0Or7d2y5lid6xjOWl7TfNB6IgQX7qR+CU5DvnbaH4Q+KH9PaOf0rq8bU8uGKEHz71RyVGTU7J7iCtfZRT7TPvy84I+UFZRV5wWf1n1eB+eiTrBbbAfPHOXalnV1/aqpsT51sx2uO10Qfbim6Rt1K0hO5TjfnL+ryWRLcKGPStDAw0YuE87g3VedNM8AK4g+kSGTepg/6iPZPY+UQaIlFRDx4O2izI9YEh3LFHoUHTPswTvvpw1wF1G8mkcx/I6vgv7qmMeL+TLWBdo4L/ZkslgsFovFYrFYLBaLxWKxWCwWi8VisVgsv8o3YIru3gAoAAA=",
};
