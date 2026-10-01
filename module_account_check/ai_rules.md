# AI Classification Contract

The deterministic checker runs first. AI is an arbitration layer for ambiguous product lineage,
RTO sequences, and competing customer transitions. It must classify only from the supplied account
and opportunity history.

## Required response

Return JSON only:

```json
{"customer_type":"...", "maintenance_status":"..."}
```

Allowed customer types:

- `Existing buyout software customer`
- `RTO customer`
- `Leasing customer`
- `PPU customer`
- `Service/Training customer`
- `Potential customer`
- `Customer by alliance`
- empty string only for Partner/Reseller or genuinely unclassified records

Allowed maintenance statuses are `Ongoing`, `Expired`, or an empty string.

## Decision rules

1. Use the exact `Account Short Name` history supplied in the request.
2. Evaluate opportunities chronologically using Close Date, then Created Date.
3. Do not invent evidence or infer opportunities that are not present.
4. Treat an incomplete RTO sequence as `RTO customer`; a completed RTO belongs to the buyout
   lineage.
5. Treat only valid Extreme subscriptions or explicit leasing/rental histories as leasing. Do not
   use unrelated cloud subscriptions as leasing. A leasing term is one year by default; use an
   explicit month/year duration in the opportunity name when present. A closed-won lease without
   a current term or later renewal is `Expired`.
6. Treat PPU according to its purchase date and stated usage period; absent an explicit period,
   use one year.
7. Treat valid buyout software and its MA/upgrade lineage as an existing buyout customer.
8. Ignore `iSLM`, `ADD`, `FEA`, and `Other` noise unless the supplied evidence clearly establishes
   a qualifying lineage outside that noise.
9. Apply the direct-relationship precedence rule:

   > Any active MA/buyout, RTO, leasing, or PPU relationship supersedes alliance activity,
   > regardless of which opportunity is newer.

10. Select `Customer by alliance` only when no active direct relationship remains. A closed-won
    OEM royalty created within six months is `Ongoing`; an older latest royalty is `Expired`.
11. A completed RTO with no following MA is `Expired`, even if an old MA was Closed Won.
12. A lost MA without a later qualifying purchase is `Expired`.
13. A current active MA or valid current direct relationship is `Ongoing`.
14. Return exactly one customer type and one maintenance status.

## AI scope and protections

AI is appropriate for unclear leasing versus cloud subscription, ambiguous RTO terms, unclear
upgrade/buyout lineage, or several competing direct histories. It is not needed for straightforward
stage/date/product cases.

The deterministic result remains authoritative for objective expiry outcomes, including completed
RTO without a following MA, lost MA without a later purchase, and expired PPU usage. Do not replace
those outcomes merely because another historical opportunity appears plausible.
