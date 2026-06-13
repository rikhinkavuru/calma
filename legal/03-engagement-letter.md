# 03 — Engagement Letter / Scope of Work (TEMPLATE)

> ⚠️ **Not legal advice.** First-draft template. A licensed attorney must review and adapt
> before use — especially the liability cap, governing law, and the no-investment-advice
> framing. Replace all `[BRACKETS]`. Pair with the NDA (`02`) and the Disclaimer (`04`,
> incorporated by reference).

---

**INDEPENDENT VERIFICATION ENGAGEMENT LETTER**

**Provider:** `[CALMA LEGAL NAME]`, a Delaware corporation ("Calma")
**Client:** `[CLIENT LEGAL NAME]` ("Client")
**Effective date:** `[DATE]`   **Engagement no.:** `[CALMA-YYYY-NNN]`

### 1. The engagement
Client retains Calma to perform an **independent computational verification** of a single,
named claim (the "Claim Under Test," **Exhibit A**) by re-executing the work that produced it
and recomputing the figure from raw outputs. Calma acts as an **independent third party**; the
verdict is produced by deterministic code.

### 2. Materials provided by Client (data bindings)
Client will provide the code, data, environment specifications, and artifacts identified in
**Exhibit A** (the "Materials"). Client represents and warrants that it has the right to provide
the Materials and that doing so does not violate any law or third-party right. **The verdict
reflects only the Materials as provided**; Calma does not independently source data or verify
that the Materials are the genuine production artifacts.

### 3. Scope of work
Calma will: (a) re-execute the Materials in an **isolated, network-denied environment** that
verifies its own isolation before running; (b) **recompute** the figure named in the Claim Under
Test from the raw output files using a reference-validated procedure; (c) **compare** the
recomputed figure to the Claim within a calibrated tolerance; and (d) issue **one verdict** —
**Confirmed**, **Refuted**, **Confirmed-with-caveats**, or **Can't-confirm** — with the measured
gap, an explicit statement of what was and was not verified, and the limits of the verification.

### 4. What is and is not verified
The verification certifies **reproducibility and the specific checks stated in the report only.**
It is **not** an audit, assurance engagement, investment recommendation, or opinion on
investment merit, and does **not** certify freedom from overfitting, data leakage, look-ahead,
or fraud unless such checks are expressly contracted in Exhibit A. The full disclaimer in
**`04-liability-disclaimer.md` is incorporated by reference** and forms part of this Agreement.

### 5. Deliverables
- A **signed verification report** (the claim, verdict, gap, scope-of-verification, limits, and
  hashes), verifiable offline with standard tooling;
- A **replay bundle** that re-derives the verdict from the recorded inputs with one command;
- A **redacted public registry entry** as described in Section 8.

### 6. Fee — prepaid and non-contingent
The fee is **`$[AMOUNT]`, fixed, due in full in advance**, and is **non-contingent and
non-refundable based on the outcome**: the fee is owed **regardless of the verdict** (Confirmed,
Refuted, Can't-confirm, or Caveated). **Calma's compensation does not depend on the result.**
Client is not purchasing a particular verdict; Client is purchasing the independent check.
`[Optional: out-of-pocket costs over $X billed at cost with pre-approval.]`

### 7. Independence
Calma will not accept any contingent, success-based, or outcome-conditioned compensation for
this engagement. The verdict is determined by deterministic code, not negotiation.

### 8. Confidentiality & public registry
The parties' NDA dated `[DATE]` (or **Exhibit C**) governs confidentiality. Client agrees Calma
may publish a **redacted registry entry** containing only the claim (as stated), metric, gap,
verdict, date, and hashes — **never** Client's code, data, or positions
`[unless Client elects an attributed entry in Exhibit A]`.

### 9. Timeline
Calma will deliver within **`[N]` business days** of receiving complete Materials and a signed
NDA. Incomplete or non-reproducing Materials may extend the timeline or result in a
**Can't-confirm** verdict with a stated fix.

### 10. Limitation of liability ⚠️ (negotiate with counsel)
**To the maximum extent permitted by law, Calma's total aggregate liability arising out of or
relating to this engagement shall not exceed the fees actually paid by Client for this
engagement.** In no event shall Calma be liable for indirect, incidental, consequential,
special, exemplary, or punitive damages, or for lost profits, investment losses, or trading
losses, even if advised of the possibility. `[Confirm cap level and any carve-outs (e.g., gross
negligence, willful misconduct, breach of confidentiality) with counsel.]`

### 11. No third-party reliance
The report is prepared solely for Client and may be relied upon **only by Client**, only for the
stated scope, and only as of its date. **No other person may rely on it** without Calma's prior
written consent. The report confers no rights on third parties.

### 12. Term & termination
This engagement covers the single Claim Under Test. Either party may terminate before delivery
on written notice; the prepaid fee is earned upon commencement of work `[or pro-rated per
counsel]`.

### 13. General
Governed by the laws of the State of `[Indiana — confirm; alt: Delaware]`, without regard to
conflicts of law; venue in `[county/state]` `[or binding arbitration — counsel to choose]`.
This Agreement, with its Exhibits, the NDA, and the incorporated Disclaimer, is the entire
agreement. Amendments must be in a signed writing. Counterparts and electronic signatures are
valid.

---

## Exhibit A — Claim Under Test & Data Bindings
- **Claim (verbatim):** `[e.g., "Net return +38%, Sharpe 2.1, 2019–2025, Strategy X"]`
- **Metric(s) and convention(s):** `[metric, risk-free, annualization, period, universe…]`
- **Code:** `[repo / commit hash / archive + hash]`
- **Data:** `[dataset identifier + hash, or pinned data binding]`
- **Environment:** `[language/runtime + dependency lock]`
- **Optional extended checks contracted:** `[none / costs-applied / walk-forward / …]`
- **Registry entry:** `[redacted (default) / attributed (Client opt-in)]`

## Exhibit B — Deliverable description
`[Signed report fields; replay-bundle contents; verification command.]`

## Exhibit C — NDA
`[Attach executed NDA or reference its date.]`

**`[CALMA LEGAL NAME]`** ____________________  Name/Title/Date
**`[CLIENT LEGAL NAME]`** ____________________  Name/Title/Date
