# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Engineer** (Monday morning): goes through the recommendation list and accepts or rejects each change (resize, stop, schedule, delete orphan). Needs the evidence, the risk and the peak-replay result to trust a change.
- **Finance**: tries off-hours policies in What-if and reads the forecast, assumptions and cost formulas. Needs to see where every rupee comes from.
- **Leadership**: reads the monthly bill and why it grew (about +40% in six months), plus the headline waste and saving.
- All three ask the same thing: "what do I do now, and how sure are we?"

## Product Purpose
SmartCloud Optimizer turns 30 days of VM utilisation data from an Indian SaaS team (50-150 VMs across Noida, Bangalore, Mumbai; prod, staging, dev) into safe, explained, costed decisions. Built for the Utho hackathon; safety of the logic and cost transparency carry most of the judging weight. Success: a user can accept a change with confidence, and can see every rupee's formula.

## Positioning
It also shows what it refused to shrink and why ("Checked and kept"), replays every downsize against 30 days of real peaks, and scores itself against generator ground truth. Each rupee carries a formula.

## Operating Context
- Read-only API (`/api/*`); accept/reject lives in the browser. Until the backend is up, the dev server answers from fallback data and the header says "Fallback data · backend offline".
- Roles switch which pages lead the navigation (Engineer, Finance, Leadership). Presets move the total live.
- Pages: Overview, Recommendations, Checked & kept, Utilization, Alerts, What-if, Forecast & Green, Data quality, Assumptions, plus a resource drawer.

## Capabilities and Constraints
- Money is in ₹ with Indian digit grouping (₹6,19,489). Numbers use tabular figures.
- Every colour is paired with a word. Green = saving, amber = Medium risk, red = High risk.
- Every number has a "how computed" tooltip.
- The API, data schema and plan are frozen (PLAN.md section 10 and 4.5; frontend/API_CONTRACT.md). The UI computes and invents no data.
- Browser tests (checkpoint gate CP01-CP16) rely on data-testid hooks, roles, labels and asserted text.
- Light theme only.

## Brand Commitments
Name: SmartCloud Optimizer. Visual authority is the Stripe-inspired frontend/DESIGN.md, which the team chose. Inter stands in for the licensed Sohne face.

## Evidence on Hand
Synthetic, seeded dataset fitted to public traces (`data/`, `generator/`). No real customers, testimonials or benchmarks exist; none may be invented.

## Product Principles
1. Answer "what do I do, and how sure are we?" before anything else on the page.
2. Show the working: formulas, evidence and the refusals, not just the result.
3. Safety over savings: a kept resource is as important as a cut one.
4. Colour is never the only carrier of meaning.
5. Calm honesty about state: fallback, mock and stale data are labelled, not hidden.

## Accessibility & Inclusion
Body text at least 4.5:1 contrast; keyboard-reachable controls with visible focus; respect prefers-reduced-motion. Indian number formatting.
