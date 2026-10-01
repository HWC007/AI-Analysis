# AI Classification Contract

The deterministic checker runs first and owns exact product, stage, date, RTO, MA, PPU, leasing, and transition rules. AI is used only for ambiguous lineage or model-transition cases.

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
- empty string only for Partner/Reseller or genuinely unclassified rows

Allowed statuses are `Ongoing`, `Expired`, or empty string. Do not invent products, stages, opportunities, account names, or reasons. An incomplete RTO is `RTO customer`; a completed RTO is buyout. Current leasing includes Extreme subscriptions and explicit leasing/rental histories. A newer alliance royalty may represent a transition from direct software to alliance.
