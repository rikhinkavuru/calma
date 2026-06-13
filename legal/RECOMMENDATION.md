# Calma — Entity & E&O Recommendation (PASS 1)

> ⚠️ **Not legal or insurance advice.** First-pass research to inform a conversation
> with a licensed attorney and a licensed insurance broker in your jurisdiction.
> Verify every number and decision with them before acting. Costs are 2026 market
> estimates and vary by state, revenue, and risk profile.

---

## 1. Entity — default call: **Delaware C-corporation from day one**

**Why C-corp, not LLC:** Calma's whole thesis points at outside capital eventually
(the investor outline, the seeder/allocator wedge). For anything venture-track, the
standard 2026 advice is to incorporate as a Delaware C-corp at the start — the
formation-cost difference is trivial, and the downside of "start LLC, convert later"
is large:

- **Conversion later costs ~$10k–$35k** in legal/filing fees and can trigger a
  taxable event if the entity holds IP or debt.
- **QSBS clock starts at incorporation (or at conversion).** Qualified Small Business
  Stock needs a **5-year hold** for the capital-gains exclusion. Starting as an LLC and
  converting in year 3 throws away three years of that clock — potentially millions at
  exit. This is the single strongest argument and it fits Calma exactly.
- **SAFEs / convertible notes are built for C-corps.** Your first seed/angel check is
  far cleaner on a C-corp cap table.
- **Liability shield** for running untrusted counterparty code is comparable under
  C-corp vs LLC, so that's a wash — the deciding factor is the fundraising/QSBS path.

**The only real case for an LLC** would be: you're certain you'll *never* raise and want
pass-through losses on your personal return. That contradicts the plan, so I'm recommending
against it.

**Realistic setup & cost:** Delaware C-corp via a formation service (Stripe Atlas ≈ $500,
or Clerky / Firstbase) → EIN (free, IRS) → founder stock issued + **83(b) election filed
within 30 days** (critical, easy to miss) → business bank + bookkeeping. Ongoing: DE
franchise tax (min ≈ $175/yr, use the assumed-par-value method to keep it low) + registered
agent (~$50–$100/yr) + **foreign-qualify in your home state** if you operate there.

**Open questions for the attorney:** your state of residence/operation (foreign
qualification + state tax), whether to reserve option pool now, and 83(b) mechanics.

---

## 2. E&O insurance — default call: **Tech E&O + Cyber, written as professional liability with an attestation/verification scope; $1M per claim / $2M aggregate to start**

**Why this shape:** Two exposures stack here. (a) **Professional liability** — you issue a
verdict a counterparty *relies on* near a capital decision; that reliance is the risk, and
it looks closer to an **auditor/attestation** risk profile than to generic IT consulting.
(b) **Cyber/data** — you take in a counterparty's code and data, so a breach/leak is a real
exposure even though you don't retain it. A **Tech E&O policy that bundles professional
liability + cyber** is the right product; it may need an attestation/assurance scope
endorsement.

**Cost ranges (estimate, expect to refine with a broker):**
- Generic solo tech E&O for $1M: ~**$1k–$3k/yr**.
- Because this is **opinion/attestation work others rely on for money**, price it higher and
  expect more scrutiny: realistically **$2k–$6k+/yr** for $1M/$2M — and at the very start,
  with no track record and a novel service, it may be **harder to place** or come with
  exclusions until you have a few engagements logged.
- Small attestation/accounting-style firms commonly carry **$1M/$2M up to $2M/$4M** limits;
  allocator clients may *require* $1M–$2M before they'll engage.

**What underwriters will ask** (and how to be ready):
- Exact services description + projected revenue + **expected # of engagements**.
- **Do you use written engagement letters with a liability cap and disclaimers?** → *Yes*
  (docs 3 & 4). Biggest premium lever.
- **Do you give investment or securities advice?** → *No.* You certify reproducibility, not
  investment merit. Keep this bright line — it's what keeps you in a coverable class and out
  of "investment adviser" exclusions.
- Data handling/security (your isolated, no-retention sandbox helps), client types (funds/
  allocators), prior claims (none), and the principal's background.

**How the cap + scope docs lower premium/risk:** a **hard liability cap** (e.g., fees paid,
or a small multiple), **explicit disclaimers** (reproducibility-only, deterministic verdict,
no reliance beyond the named client and stated scope), a **defined single-claim deliverable**,
and **prepaid + non-contingent** terms (no incentive to please the verified party) all
materially de-risk the engagement. Underwriters reward exactly this. Build docs 3 & 4 to be
shown to the broker.

**Watch-outs to raise with the broker:**
- Many tech-E&O forms **exclude financial/investment advice and express guarantees/
  warranties** — confirm your verification opinions are *covered* and your disclaimers keep
  you clear of the investment-advice exclusion.
- Use a **startup-savvy broker** (e.g., Vouch, Embroker — both bundle Tech E&O + Cyber + D&O)
  and/or a **professional-liability specialist** comfortable with attestation/assurance
  (the accountants'-PL market: CAMICO, Berkley, CFC, The Hartford). Get 2–3 quotes.

---

## How the two decisions interlock
The **C-corp** keeps the fundraising/QSBS path clean; the **liability cap + disclaimers +
prepaid/non-contingent terms** in the engagement docs are simultaneously the thing that makes
E&O **placeable and cheaper**. So PASS 2's docs 3 & 4 should be drafted with the broker's
underwriting questions in mind — they do double duty (sell the engagement *and* lower premium).

## Recommended next steps (after your sign-off)
1. PASS 2: draft docs 1–5, with entity = DE C-corp and insurance = bundled Tech E&O + Cyber.
2. Engage a startup attorney for formation + to review the NDA / engagement letter / liability
   language.
3. Get 2–3 E&O quotes from a startup broker, leading with the scope + cap + no-investment-advice
   posture.

---

### Sources
- [Delaware C-Corp vs LLC for Startups — 2026 Decision Guide (ICanPitch)](https://www.icanpitch.com/blog/delaware-c-corp-vs-llc-startups-guide)
- [How to Incorporate Your Startup in 2026: Why Delaware C-Corp Is Still King (Flux)](https://www.flux.law/blog/how-to-incorporate-startup-delaware-c-corp)
- [LLC vs C-Corp: the venture-fundability fork and conversion math (Startups.com)](https://www.startups.com/lexicon/llc-vs-c-corp)
- [Converting Your LLC to a Delaware C-Corp (Flux)](https://www.flux.law/blog/convert-llc-to-delaware-c-corp)
- [Average Errors and Omissions Insurance Cost — 2026 (MoneyGeek)](https://www.moneygeek.com/insurance/business/e-o-cost/)
- [2026 Guide to Tech E&O Insurance Requirements (MoneyGeek)](https://www.moneygeek.com/insurance/business/tech-e-o-insurance/)
- [Professional Liability (E&O) Insurance for Consultants (Insureon)](https://www.insureon.com/consulting-business-insurance/professional-liability)
- [Accountants Professional Liability — New Business app (Berkley Select, PDF)](https://www.berkleyselect.com/sites/g/files/xkzibx191/files/2023-12/Select_AccountantsProfessionalLiabilityInsruance_NewBusiness.pdf)
- [Professional Indemnity Insurance for Auditors (The Hartford)](https://www.thehartford.com/professional-liability-insurance/auditors)
