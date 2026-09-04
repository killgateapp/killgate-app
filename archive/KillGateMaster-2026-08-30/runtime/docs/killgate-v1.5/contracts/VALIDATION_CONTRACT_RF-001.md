# Validation Contract — RF-001

**Status:** LOCKED  
**Contract version:** 1.0  
**Created/locked:** 2026-08-27T08:24:00Z (before evidence scoring)  
**Hypothesis:** Independent HVAC companies with 3–15 field technicians that already use digital scheduling/dispatch lose enough same-day productive capacity from cancellations—while other customers remain waitlisted—that they will pay $149/month for up to 10 technicians ($10/month each additional) for an add-on that integrates with the existing scheduler, detects newly opened gaps, and automatically offers the slot to geographically and operationally suitable waiting customers until one accepts, recovering at least one otherwise-lost service call per month.

**Fingerprint:** hvac-indie-3to15-149-routefill-gap-backfill

## Provisional assumptions
- Buyer is owner/ops manager with card authority.
- Company already pays for ServiceTitan, Housecall Pro, Jobber, FieldEdge, or similar.
- RouteFill is an integration add-on, not a system of record.
- Geography is US/Canada field service HVAC (founder unspecified).

## Mechanisms scored separately (not inherited)
- M1: Confirmation/cancellation SMS creates earlier notice of a dropped appointment.
- M2: Integration can detect a newly opened gap in the incumbent scheduler in time to act.
- M3: Matching on proximity, service type, tech capability, duration, and drive time yields a feasible same-day candidate.
- M4: Automated offer-until-accept converts that candidate into a filled slot.
- M5: Recovering ≥1 otherwise-lost call per month causes payment of $149 (plus seat overage).

Evidence that SMS reminders do or do not reduce no-show *rates* does not prove or disprove M3 or M4.

## Critical assumptions
1. Target HVAC firms experience recurring same-day cancels that idle technicians.
2. Those gaps coincide with waitlisted demand that could physically be served.
3. Current workarounds (dispatcher callback, overbooking, leftover maintenance, send tech home) leave money on the table.
4. Route-aware auto-offer is better on a dimension they value than manual fill or features already in the scheduler.
5. Owner can add $149/mo on top of existing software.
6. $149 + SMS/10DLC + integration cost + HVAC sales CAC can work.
7. Qualified buyers will pay a real $149 pilot.

## Locked gates
Default Killgate research and human/economic numeric gates. Unchanged. Research pass ≠ permission to build. GO requires 8 qualified buyers, ≥30% strong pain with recent examples, 4 price-positive unless 2 paid, 2 verified paid pilots, objections recorded.
