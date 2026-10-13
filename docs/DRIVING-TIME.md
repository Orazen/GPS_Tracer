# Driving-time calculations

**Status: implemented, unit-tested, and NOT validated against a reference. Do not
present any figure in this system as a legal finding.**

That sentence is the most important thing on this page. The rest explains exactly
what is implemented, what every assumption is, and what would have to happen before
anyone could responsibly use this for compliance rather than for visibility.

Rules version: `eu-561-2006/2026.1`
Engine version: `driving-time/0.1.0`

---

## 1. Why there is a version string on every result

Every stored calculation names the rules version, the engine version, the calendar
days it was computed from, the import IDs behind those days, and every assumption it
made. When the rules change, existing rows are **never rewritten** — a new run is
inserted alongside. Anyone looking at an August figure can see it came from rules
`2026.1`, not from today's engine.

Without that, "why does the report say 9h20 when I remember 9h" has no answer. With
it, the answer is one query.

---

## 2. Legal basis

The figures come from **Regulation (EC) No 561/2006** as amended, principally by
**Regulation (EU) 2020/1054**. Article numbers are cited on every finding the engine
emits, so a human can check the engine instead of trusting it.

The amendment history was checked deliberately, because it is where a "known" figure
turns out to be stale: 2020/1054 changed the rest and compensation arrangements, the
multi-manning break rule, the ferry/train rule and the ban on taking regular weekly
rest in a vehicle. It did **not** change the daily 9/10-hour cap, the twice-per-week
extension, the 56-hour weekly cap, the 90-hour two-week cap, or the 45-minute break
with its 15-then-30 split.

> **Not every source agrees on the details.** The authoritative EUR-Lex HTML for the
> consolidated regulation and for 2020/1054 could not be read during research; the
> figures below were confirmed against the published provision texts and Commission
> guidance. Before this is used for anything that matters, the rule set must be
> re-checked against the consolidated text. This is recorded because a compliance
> tool that hides which sources it relied on is worse than one that has none.

**Out of scope by design:** Regulation (EU) 2024/1258 adds flexibility for
*occasional passenger transport*. This deployment serves goods transport, and that
regulation is **not implemented**. Do not apply this engine to passenger services.

---

## 3. What is implemented

### Article 6 — driving limits

| Rule | Limit | Article |
|---|---|---|
| Daily driving | 9 h, extendable to 10 h at most **twice per week** | Art 6(1) |
| Weekly driving | 56 h | Art 6(2) |
| Two consecutive weeks | 90 h | Art 6(3) |
| Week definition | Monday 00:00 → Sunday 24:00 | Art 4(i) |

Findings emitted: `daily_driving_exceeded_absolute`,
`daily_driving_extension_too_often`, `weekly_driving_exceeded`,
`fortnightly_driving_exceeded`, `fortnightly_driving_unassessable`.

### Article 7 — the break after 4.5 hours

A **driving period** (Art 4(q)) is accumulated driving since the last break or rest.
It **spans midnight and therefore several daily records**, which is why the engine
walks merged blocks across day boundaries rather than computing per day. A per-day
implementation misses exactly the violation a fleet most needs to see.

A qualifying break is **45 uninterrupted minutes**, or **parts of at least 15 minutes
each summing to 45**. Commission guidance specifies the order as 15 then 30; the
engine requires the parts to be individually ≥ 15 minutes and to total 45, and it
records the observed part sizes as evidence so the ordering can be checked rather
than assumed.

**Only recorded break/rest counts.** Other work and availability neither accumulate
driving nor satisfy the break requirement (Art 4(d): a break is used *exclusively*
for recuperation; Art 6(5) requires them to be recorded separately). A 20-minute
break does not reduce the 4.5 hours either — under 15 minutes does not count at all.

Findings: `driving_period_without_qualifying_break`, `break_rule_gap_in_record`,
`break_rule_unassessable_open_record`.

### Article 8 — daily and weekly rest

| Rule | Figure | Article |
|---|---|---|
| Regular daily rest | ≥ 11 h | Art 4(g) |
| Reduced daily rest | ≥ 9 h and < 11 h | Art 4(g) |
| Split daily rest | ≥ 3 h then ≥ 9 h (≥ 12 h total) | Art 4(g) |
| Reduced daily rests between two weekly rests | at most 3 | Art 8(4) |
| Daily rest window | within 24 h of the end of the previous daily/weekly rest | Art 8(2) |
| Multi-manning | 9 h within 30 h | Art 8(5) |
| Regular weekly rest | ≥ 45 h | Art 4(h) |
| Reduced weekly rest | ≥ 24 h | Art 4(h), Art 8(6) |
| Compensation | equivalent rest, en bloc, before the end of the third week following, attached to a rest of ≥ 9 h | Art 8(6b) |
| Next weekly rest due | within six consecutive 24-hour periods of the previous one | Art 8(6) |

Rest is reported **as observed**, and the engine deliberately does not assert
compliance. The reason is structural: Art 8(2) anchors the 24-hour window on the end
of the *previous* rest, which a period starting mid-history cannot reconstruct. So
the engine reports what the records show and marks the rest `unknown` where they do
not support a conclusion.

Findings: `reduced_daily_rest_count`, `weekly_rest_not_found`,
`weekly_rest_unassessable_partial_week`, `weekly_rest_reduced_compensation_required`,
`rest_block_below_daily_rest_minimum`, `rest_block_open_at_end_of_data`,
`daily_rest_unassessable_no_rest_recorded`, `weekly_rest_unassessable_no_rest_recorded`.

### Also implemented

- **Staleness.** If the newest record is more than 21 days old the status becomes
  `stale` and remaining hours are not presented. Presenting last month's driving time
  as today's is the specific failure the specification warns about.
- **Coverage.** `status` becomes `insufficient_data` whenever a day in the period is
  missing or a record contains time with no card.
- **Multi-manning awareness.** Co-driver rows are kept and passed to the engine
  rather than discarded, because multi-manning changes which limit applies.

---

## 4. Assumptions, recorded on every result

These are emitted verbatim in the `assumptions` array of every calculation:

1. Activity times are the local wall clock stored in the file; **no timezone
   conversion and no daylight-saving shift** is applied. Two days a year this is
   wrong by an hour.
2. Only recorded break/rest counts as a break. Other work and availability do not
   interrupt a driving period.
3. Gaps in the records are treated as **unknown, never as rest**.
4. Week boundaries are Monday 00:00 to Sunday 24:00.
5. Working time under Directive 2002/15/EC **is not assessed**. Satisfying a
   driving-time limit does not establish working-time compliance.
6. Regulation (EU) 2024/1258 is not implemented; this is goods transport.
7. Daily rest is reported as observed, not as an assertion of compliance.

---

## 5. The safety rails, and how they are enforced

Four rules the code cannot break, and where each is held:

| Rail | Enforcement |
|---|---|
| A result is never marked legally validated | `CalculationResult.validated_against_reference` is a literal `False`; no code path sets it True. `test_result_is_never_marked_validated` asserts it. The database column defaults to `false` and its `COMMENT` records that no row is true. |
| Gaps never become rest | `_rest_blocks` refuses to bridge a gap between records; `test_rest_is_never_inferred_across_a_gap` asserts the block structure, not just the absence of a finding. |
| No invented compliance at the end of a record | A record that stops mid-activity is reported `unknown` with `actual_minutes = None`, never as a breach and never as compliant. |
| The rules version travels with the number | `rules_version` and `engine_version` are columns on `tacho_calculations` with an index on `rules_version`. |

---

## 6. Verification status: what has and has not been done

| Claim | Status | Evidence |
|---|---|---|
| Daily/weekly/fortnightly limits computed correctly | ✅ **tested** | Hand-computed scenarios in `tacho/tests/test_driving_time.py` |
| Week boundaries are Monday-based | ✅ **tested** | `test_extensions_are_counted_per_calendar_week_not_per_fortnight`, `test_weeks_are_split_on_monday` |
| The 4.5-hour period spans midnight | ✅ **tested** | `test_the_driving_period_crosses_midnight` |
| Other work/availability does not satisfy a break | ✅ **tested** | `test_other_work_does_not_satisfy_the_break`, `test_availability_does_not_satisfy_the_break_either` |
| 15-then-30 split, and that 15 alone is insufficient | ✅ **tested** | `test_the_split_fifteen_then_thirty_resets_the_period`, `test_fifteen_alone_does_not_satisfy_the_break` |
| Three reduced daily rests allowed, four flagged | ✅ **tested** | `test_three_reduced_daily_rests_are_allowed`, `test_four_reduced_daily_rests_are_flagged` |
| A week with no weekly rest is a breach | ✅ **tested** | `test_a_full_week_with_no_long_rest_is_a_breach` |
| Stale data is reported stale | ✅ **tested** | `test_stale_data_is_reported_as_stale_and_not_calculated_as_current` |
| The weekly limit cannot be exceeded without a companion breach | ✅ **tested** | `test_the_weekly_limit_cannot_be_exceeded_within_the_other_limits` — a useful invariant: a report showing *only* a weekly breach has a bug |
| **Agreement with a trusted tachograph analysis report** | ❌ **NOT RUN** | No reference report has ever been available. This is the validation the specification asks for and it remains outstanding. |
| **Agreement with a real driver card** | ❌ **NOT RUN** | No lawfully obtained real `.DDD` file has been available. See `docs/TACHO-SERVICE.md` § Verification status. |
| **Multi-manning (Art 8(5)) end-to-end** | ⚠️ **PARTIAL** | Co-driver rows are parsed and retained; the 30-hour/9-hour rule is defined as constants but is not assessed as a finding. A mixed-crew file has not been tested. |
| **Weekly-rest compensation actually taken** | ⚠️ **NOT IMPLEMENTED** | The engine flags that compensation is *required*; it does not verify it was taken. Recorded as `compensation_verified: false` in the evidence. |
| **Working time (2002/15/EC)** | ❌ **NOT IMPLEMENTED** | Out of scope by design; stated on every result. |

---

## 7. What would have to happen before this is used for compliance

In order, and none of it is optional:

1. **A real driver card and a real vehicle-unit file**, lawfully obtained, covering
   at least a week of mixed activity including a night out and a multi-manning day.
2. **A trusted analysis report** for those same files, from a commercial analysis
   provider or an enforcement-recognised tool.
3. **A comparison test** that reconciles every figure — daily driving, weekly,
   fortnightly, every break, every daily and weekly rest — and records the
   differences rather than only the matches.
4. **Reconciliation of the assumption list** in §4 against how the operator actually
   runs: their shift patterns, their timezone, whether they cross a DST boundary in
   period, and whether they use multi-manning.
5. **Only then**, flip `validated_against_reference` for those specific runs and
   record `validation_note` naming the reference. Not a code change to the default —
   a per-run, documented claim.

Until step 5, the honest wording in any UI or report is: **"recorded activity and
calculated figures, not a legal finding."**
