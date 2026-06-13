# 02 — Mutual Non-Disclosure Agreement (TEMPLATE)

> ⚠️ **Not legal advice.** First-draft template. A licensed attorney must review and
> adapt before use. Bracketed terms are placeholders. This NDA is mutual but is written
> for the situation where **Calma receives a counterparty's code and data** to perform a
> verification engagement.

---

**MUTUAL NON-DISCLOSURE AGREEMENT**

This Mutual Non-Disclosure Agreement ("Agreement") is entered into as of `[DATE]` ("Effective
Date") by and between **`[CALMA LEGAL NAME]`, a Delaware corporation** ("Calma"), and
**`[COUNTERPARTY LEGAL NAME]`** ("Counterparty"). Each may be a "Disclosing Party" or
"Receiving Party."

### 1. Purpose
The parties wish to explore and/or perform an independent computational-verification
engagement, under which Counterparty may provide Calma with source code, data, configuration,
and related materials, and the parties may exchange other confidential information (the
"Purpose").

### 2. Confidential Information
"Confidential Information" means non-public information disclosed by a Disclosing Party that is
marked confidential or that a reasonable person would understand to be confidential, including
without limitation Counterparty's **source code, datasets, models, parameters, strategies,
positions, and results**, and Calma's methods, tooling, and non-public materials.

### 3. Obligations of the Receiving Party
The Receiving Party shall: (a) use Confidential Information solely for the Purpose; (b) not
disclose it to third parties except to employees, contractors, or advisors with a need to know
who are bound by confidentiality obligations at least as protective as this Agreement; and
(c) protect it with at least reasonable care.

### 4. Calma's handling of Counterparty materials (engagement-specific)
For any code, data, or materials Counterparty provides for a verification engagement, Calma
shall:
- (a) **Process them only within an isolated execution environment** with network egress
  denied by default, used solely to perform the engagement;
- (b) **Not retain** Counterparty's source code or raw datasets beyond **`[30]` days** after
  delivery of the final report, and **securely delete** them thereafter, except (i) materials
  Calma must retain to support or re-derive its verdict and (ii) as required by law — in each
  case kept confidential under this Agreement;
- (c) **Not use** the materials to develop competing strategies or for any purpose other than
  the engagement.

### 5. Permitted public output (redacted registry entry)
Counterparty acknowledges and agrees that Calma maintains a public, append-only verification
registry, and that **Calma may publish a redacted registry entry** for the engagement
containing only: the **claim under test (as stated), the metric, the measured gap, the verdict,
the engagement date, and cryptographic hashes** of the inputs/outputs. Calma shall **not**
publish Counterparty's source code, raw data, positions, or identity-revealing details
`[unless Counterparty separately consents in the Engagement Letter]`. Publication of a redacted
registry entry as described is **expressly permitted and is not a breach** of this Agreement.

### 6. Exclusions
Confidential Information does not include information that: (a) is or becomes public through no
fault of the Receiving Party; (b) was rightfully known without obligation before disclosure;
(c) is rightfully received from a third party without restriction; or (d) is independently
developed without use of the Confidential Information.

### 7. Compelled disclosure
If legally compelled to disclose, the Receiving Party may do so after giving prompt notice (to
the extent legally permitted) and reasonable cooperation to allow the Disclosing Party to seek
protection.

### 8. Return or destruction
Upon request or upon termination of the Purpose, the Receiving Party shall return or destroy
Confidential Information, subject to Section 4(b) and standard backup-retention exceptions.

### 9. No license; no warranty
No license or ownership is granted. Confidential Information is provided "AS IS," without
warranty.

### 10. Term
This Agreement applies to disclosures made for `[two (2)]` years from the Effective Date, and
confidentiality obligations survive for `[three (3)]` years after disclosure — provided that
**trade secrets** remain protected for as long as they qualify as trade secrets under
applicable law.

### 11. No obligation; remedies
Nothing obligates either party to proceed with an engagement. The parties agree that monetary
damages may be inadequate and that **injunctive relief** may be sought for breach.

### 12. General
This Agreement is governed by the laws of the State of `[Indiana — confirm; alt: Delaware]`,
without regard to conflicts of law. It is the entire agreement on its subject matter, may be
amended only in a signed writing, and may be signed in counterparts (including electronically).

**`[CALMA LEGAL NAME]`**  ___________________________  Name/Title/Date

**`[COUNTERPARTY LEGAL NAME]`**  ___________________________  Name/Title/Date
