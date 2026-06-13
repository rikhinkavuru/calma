# 01 — Entity Formation & Compliance Checklist

> ⚠️ **Not legal/tax advice.** First-draft checklist for a Delaware C-corporation
> operating in Indiana. Confirm every step, fee, and deadline with a licensed
> attorney and CPA. Fees are 2026 estimates and change.

**Decision (approved):** Delaware C-corporation, formed day one (not an LLC). Rationale
in `RECOMMENDATION.md` — fundraising path, SAFE/convertible compatibility, and the QSBS
5-year clock starting at incorporation.

---

## A. Form the Delaware C-corp
- [ ] **Choose a formation path:** Stripe Atlas (~$500, bundles incorporation + EIN + stock + templates), Clerky, or Firstbase — or a startup attorney directly. *Atlas/Clerky are standard for venture-track solo founders.*
- [ ] **Name check** + incorporate (file Certificate of Incorporation with Delaware Division of Corporations).
- [ ] **Authorize shares:** typical seed-stage default ~10,000,000 authorized common shares; issue founder shares, keep the rest for an option pool / future rounds. *(Confirm count with counsel.)*
- [ ] **Delaware registered agent** (required; ~$50–$100/yr, included by Atlas/Clerky year one).
- [ ] **Adopt bylaws**, appoint initial director(s) (you), hold/just-document the initial board action by written consent.

## B. Founder stock + the 83(b) election ⏰
- [ ] **Issue founder stock** and pay for it (even a nominal amount; document the purchase).
- [ ] **File the 83(b) election with the IRS within 30 calendar days of issuance.** *(Hard deadline, no extensions. Missing it can create a large future tax bill. Even at near-zero value, file it.)* Keep proof of mailing.
- [ ] Decide on vesting (often a single-founder skips or self-imposes a schedule for future investors' comfort — ask counsel).

## C. Federal setup
- [ ] **Get an EIN** from the IRS (free, irs.gov; Atlas does this for you). Needed for bank + taxes.
- [ ] Confirm **C-corp federal tax filing** obligations (Form 1120) with a CPA; set a fiscal year (usually calendar).

## D. Qualify to do business in Indiana (foreign qualification)
*A Delaware corporation operating in Indiana must register there.*
- [ ] Obtain a **Delaware Certificate of Good Standing** (a.k.a. certificate of existence).
- [ ] File an **Application for Certificate of Authority** as a foreign corporation with the **Indiana Secretary of State via INBiz** (inbiz.in.gov). *(Estimated fee ~$90–$125; confirm current.)*
- [ ] Appoint an **Indiana registered agent** (you at your IN address, or a commercial agent).
- [ ] Register with the **Indiana Department of Revenue** (INTIME) for state tax accounts as applicable (corporate income / adjusted gross income tax; sales tax only if selling taxable goods — verification services likely not, confirm with CPA).

## E. Banking & accounting
- [ ] Open a **business bank account** (Mercury and Brex are startup-standard; or a local Indiana bank). Keep personal and business funds strictly separate (preserves the liability shield).
- [ ] Set up **bookkeeping** (QuickBooks / Pilot / Bench) and a CPA for annual 1120 + Indiana returns.
- [ ] Track every engagement's revenue separately (helps E&O underwriting and the registry's prepaid/non-contingent record).

## F. Ongoing compliance (calendar these)
- [ ] **Delaware annual franchise tax + report:** due **March 1** each year. Use the **assumed-par-value capital method** to keep it low (often ~$400–$450 total incl. report; the authorized-shares method can balloon to thousands — choose the right method). Registered agent renewal annually.
- [ ] **Indiana Business Entity Report:** corporations file **biennially** (every 2 years) via INBiz (~$30 online). Calendar it.
- [ ] **Federal + Indiana income tax** filings annually (CPA).
- [ ] **BOI / beneficial ownership** reporting — confirm current FinCEN requirements with counsel (rules have shifted; verify what applies in 2026).
- [ ] **Bind E&O + Cyber insurance** before the first engagement (see `05`).

## G. Pre-fundraise hygiene (since you intend to raise)
- [ ] Keep a clean **cap table** (Carta / Pulley, or a simple spreadsheet to start).
- [ ] Use **standard SAFEs** (Y Combinator post-money SAFE) for early checks — built for C-corps.
- [ ] Assign all IP to the company (founder IP assignment agreement) — investors will diligence this.
- [ ] Preserve **QSBS eligibility** (C-corp, gross assets under threshold at issuance, active business) — ask counsel/CPA to confirm you qualify and document it.

### Open items for counsel/CPA
- Indiana governing-law vs Delaware for customer contracts (see `03`).
- Whether to set up an option pool now.
- State nexus/tax if you take engagements from out-of-state clients.
- Current BOI/FinCEN status.
