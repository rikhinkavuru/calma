/* StackMarquee — real brand logos via the Simple Icons CDN, monochrome,
   lighting up on hover, sliding right-to-left into an abyss on both edges. */
export function StackMarquee() {
  const items: [string, string][] = [
    ["Python", "python"],
    ["pandas", "pandas"],
    ["NumPy", "numpy"],
    ["Polars", "polars"],
    ["DuckDB", "duckdb"],
    ["PostgreSQL", "postgresql"],
    ["Apache Spark", "apachespark"],
    ["Apache Arrow", "apachearrow"],
    ["scikit-learn", "scikitlearn"],
    ["Snowflake", "snowflake"],
    ["Databricks", "databricks"],
    ["Jupyter", "jupyter"],
  ];
  const loop = items.concat(items);
  return (
    <div className="marq" aria-label="Reads your existing pipeline">
      <div className="marq__track">
        {loop.map(([name, slug], i) => (
          <span className="marq__item" key={i}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="marq__logo" src={"https://cdn.simpleicons.org/" + slug} alt="" width="19" height="19" loading="lazy" />
            <span className="marq__name mono">{name}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
