"use client";

// The upgrade popup: shown when a lower tier attempts something only a higher tier can do. The backend is the
// authority — it returns a 402 with a plain-language reason (core.limits gates) — and this renders that reason
// with a path to plans. Also usable proactively (a locked control passes its own reason).
import Link from "next/link";
import { FiLock, FiX, FiArrowUpRight } from "react-icons/fi";
import dash from "./dashboard.module.css";

export function UpgradeModal({ reason, onClose }: { reason: string | null; onClose: () => void }) {
  if (!reason) return null;
  return (
    <div className={dash.modalOverlay} role="dialog" aria-modal="true" onClick={onClose}>
      <div className={dash.modal} onClick={(e) => e.stopPropagation()}>
        <button className={dash.modalClose} onClick={onClose} aria-label="Close">
          <FiX />
        </button>
        <div className={dash.modalIcon}>
          <FiLock />
        </div>
        <h3 className={dash.modalTitle}>A paid feature</h3>
        <p className={dash.modalBody}>{reason}</p>
        <div className={dash.modalActions}>
          <Link href="/pricing" className={`${dash.btn} ${dash.btnAmber}`}>
            See plans <FiArrowUpRight />
          </Link>
          <button type="button" className={`${dash.btn} ${dash.btnGhost}`} onClick={onClose}>
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
