# Verification — 2026-10-18

## Scope delivered

Grow local web: year/month/week/day hierarchy, optional parent, explicit short/long horizon, target-count progress, priority homepage, typed study navigation, recoverable execution, minimum/full/interrupted outcomes, foreground reminders/snooze and calendar export, private manual reviews/drafts/history and opt-in AI summaries/suggestions. Native LightTick integration is a design deliverable in `/Users/hao/Documents/project/plan/docs/04-planning/grow-action-plans-lighttick-v1-2026-10-18.md`.

Existing unrelated local changes were preserved. No native or Zook runtime/contract changes, real-account binding, migration, commit or push were performed for this feature.

## Automated checks

Final command:

```sh
TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao' PYTHONPATH=知行成长/server:知行成长/server/tests 知行成长/.venv/bin/python -m unittest test_action_reviews test_study_notes test_study_materials test_local_server_environment
node 知行成长/server/tests/test_action_plan_client.cjs
node --check 知行成长/server/static/action-plans.js
node --check 知行成长/server/static/action-reviews.js
openspec validate action-plans-v1 --strict
git diff --check
```

Python: 31 discovered, **30 passed, 1 skipped**, no failures. The skipped test is the existing `RUN_GITHUB_BROWSER=1` optional Chrome route check; actual browser acceptance below used the app browser. Node transport checks, syntax checks, OpenSpec validation and whitespace checks passed.

Coverage includes all four hierarchy levels; monthly boundaries; tenant separation; additive schema upgrade from the earlier action-plan schema; stale and concurrent mutations; one running session; duplicate start/finish retries; separate course/note state; business timezone, quiet hours and reminder claims; exact-preview consent; missing AI settings; changed-context rejection; provider failure sanitization; interrupted generation recovery; optional text selection and truncation while retaining complete aggregate totals; request-scoped credentials absent from retry storage and database results.

Fixtures use a disposable localhost PostgreSQL schema and mocked model transport. No remote production database was used for test writes, and no paid model call was made.

## Browser acceptance

Used the app browser with `tests/serve_action_plans_fixture.py`, real action/material/note APIs and synthetic learning content. The deterministic model replacement was injected only by this fixture.

1. Created annual goal → October plan → current week → today's action, using visible UI forms. Correct default dates, parent labels and short/long classification displayed.
2. Confirmed homepage puts the due action before courses, shows its intention and start options, and displays a persistent due banner.
3. Started the 5-minute variant and entered the structured-expression reader. Saved a practice answer and note independently; the reader explicitly remained incomplete.
4. Reloaded; active execution returned. Recorded 5 minutes minimum; pending action remained available and goal success stayed zero.
5. Started again, confirmed the answer/note had restored, and saved a 2-minute interruption. Started once more and confirmed 20 minutes completed.
6. All four levels displayed **27 actual minutes, one success and one minimum execution**. History separately displayed 20-minute success, 2-minute interruption and 5-minute minimum. The course still remained incomplete.
7. Homepage recognized today's one completed action and 27 minutes; week progress was 1/5. Long-term filter showed the annual goal; short-term filter showed month/week/day.
8. Opened monthly review; scoped statistics showed 27 minutes, one success, one minimum/partial and one interruption. Entered three review fields, closed/reopened to recover the draft, then saved and saw history.
9. AI without configuration showed a clear settings message. Configured an obviously dummy key for the isolated model, selected execution notes and saved reviews, refreshed the exact preview, then confirmed generation. The UI showed generating status; closing and reopening recovered the saved summary and suggestions.
10. “参考建议，手动调整计划” opened the normal editor. Explicitly changed the monthly default time and saved; historical facts stayed intact.
11. Created tomorrow's paper-book action; it did not become today's action. Downloaded `.ics` through the visible calendar link and checked `DTSTART:20261019T130000Z` for 21:00 Asia/Shanghai plus `BEGIN:VALARM`. Paused it and verified it left the pending list.
12. Browser warning/error logs were empty for both the fixture and real main page at the final check.

Evidence (local ignored QA artifacts):

- `/Users/hao/Documents/grow/.gstack/action-plans-2026-10-18/home.png`
- `/Users/hao/Documents/grow/.gstack/action-plans-2026-10-18/progress.png`
- `/Users/hao/Documents/grow/.gstack/action-plans-2026-10-18/review.png`

## Real local service

Restarted `http://localhost:8756/` with final sources through `server/run_local.py`. Health returned HTTP 200. Existing owner login restored without re-entering credentials. Read-only browser verification showed the new navigation, four create-period buttons, horizon/status filters, an empty personal plan state, and the existing course completion counts after returning home. No synthetic plans, notes or reviews were written to this real account.

## Limits

- Real model-provider connectivity and output quality were not tested; the implementation uses the existing compatible transport and the user's own configuration.
- Browser/OS notification permission prompts, imported calendar delivery, mobile background delivery and native iOS/Android integration were not exercised. The web UI accurately describes page-open reminders and independent calendar imports.
- Generation recovery currently assumes the existing single-worker local deployment; a shared cross-worker lease is required before horizontal workers.
- Native identity binding, single-writer migration, contract extension, builds and device acceptance remain future work described in the handoff document.
