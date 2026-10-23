# Recording matching

Native spelling is preserved for display and is the first search variant.
AnyAscii supplies an additional Latin transliteration for search and comparison;
it is not translation or language-aware pronunciation. Proven spelling aliases
remain available because transliteration cannot infer all official artist names.

`compare_recordings()` returns `match`, `different`, or `unverified`, a similarity
score, separate title/performer percentages, timing/ISRC evidence and reason codes.
The score is **not a calibrated probability of correctness**. Missing evidence is
not a positive match. The weighted score uses title 55, performers 35, duration 10;
unavailable duration is omitted and other weights are normalized.

Guest credits (`feat.`, `ft.`, `featuring`, bracketed `with`) are extracted into
performer identities. Punctuation, case and word order can vary. Musical versions
are preserved: live, remix, instrumental, opening, cover etc. Unbracketed `with`
is not stripped because it occurs in actual titles such as Die With A Smile.

For automatic links the entire performer set must match natively or through
transliteration. Transliterated performer identities require supporting timing
or ISRC evidence. Transliterated titles also require matching timing unless ISRC
confirms the recording. Partial words or title similarity alone are insufficient.
Different ISRC values require review; a matching ISRC still cannot override
conflicting performers, duration or an explicit differing version.

Candidates that pass these checks are ordered by evidence score in Spotify,
Apple Music and Yandex. Album matches are used as tie breakers. Known verified
source URLs remain unchanged. YouTube candidates still pass the same identity
checks; official video verification and group-cover metadata handling remain.

The local catalogue stores both original and transliterated search terms using
the original stable track identifier. Search snapshots retain the existing lazy
refresh lifecycle; personal Spotify playback is not cached in the catalogue.

Each query snapshot records a search revision derived automatically from the
search/provider code, pinned dependencies and duration tolerance setting. After
an update, an older snapshot remains readable but is due for background refresh
even if its normal 12-hour refresh interval has not elapsed. Old retry cooldowns
do not suppress the first attempt under a new revision. During revalidation the
bot bypasses old catalogue cross-links and local result supplementation; an empty
or failed service refresh never marks the old snapshot as checked. Concurrency,
provider quotas and retry cooldowns still apply; deployments do not mass-query
all historical searches or reset quota counters.

Inspect candidates and decisions without starting the bot:

```sh
python scripts/diagnose_search.py --cases tests/live/user_confirmed.json --verify-metadata --candidates
```

This performs live API calls and consumes provider quota. Reports include
candidate title, performer, URL, similarity components, status and reason codes.
