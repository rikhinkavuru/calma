"use client";
import { useFormStatus } from "react-dom";
import { submitDemoAction } from "../actions";
import styles from "../dashboard.module.css";

function Btn() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={styles.btn} disabled={pending}>
      {pending ? "Running the demo…" : "Run the demo →"}
    </button>
  );
}

// One-click: submit a bundled sample backtest through the real pipeline. No bundle to build, no
// verify.yaml to write — the user sees the full re-execute → recompute → verdict loop immediately.
export function DemoButton() {
  return (
    <form action={submitDemoAction}>
      <Btn />
    </form>
  );
}
