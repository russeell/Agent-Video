# Find videos with Agent Video

Read this guide when the user wants to find videos. The host agent searches and judges relevance; Agent Video checks selected links and reads their content when needed. It does not install or run a search service.

## Search within the requested platform

Use the user's platform, then the current video task's platform, otherwise YouTube with a brief explanation. Search across platforms only when asked.

Check which host search tools actually work. A configured tool is not necessarily reachable. Prefer a working platform search tool or a web search restricted to that platform:

| Platform | Useful search path |
|---|---|
| YouTube | Host search or a site-scoped web search for watch / Shorts links |
| Bilibili | Host Bilibili search, including its public video-search API, or a site-scoped web search |
| TikTok | Site-scoped web search for individual videos; try another available search provider if the first returns only topic or shop pages |
| Douyin | Site-scoped web search for individual works; anonymous on-site search may require interactive verification even when individual videos are readable |

For example, **if Exa via mcporter is available**, this returns candidates without downloading videos:

```bash
mcporter call 'exa.web_search_exa(query: "site:tiktok.com aliens UFO", numResults: 5)'
```

Use the user's topic; adapt keywords when useful, such as `外星人`, `aliens` or `UFO`. Keep queries and candidates small. If one provider fails, try a suitable available alternative within the same platform; avoid repeatedly retrying a blocked search.

## Keep real video candidates

Keep links that identify one video: YouTube watch / Shorts, Bilibili BV / av, TikTok `@user/video/ID`, or Douyin `video/ID` / `modal_id`. Resolve supported share links when necessary. Search pages, topics, shops, channels, profiles and photo posts are not single-video results.

Deduplicate by platform and work ID; include the selected Bilibili part in the identity. Remove irrelevant tracking parameters; do not guess a repair for a malformed link. Preserve each candidate's link and search title until checked. A result lacking duration or spoken language has unknown fields, not inferred values.

For a small shortlist, check actual video information:

```bash
"<skill_dir>/.venv/bin/agent-video" "<candidate-url>" --get info
```

Open the returned metadata and keep its canonical URL, ID, title, duration and manifest. Use the checked duration for the selected Bilibili part: search results may show the entire multi-part work's duration. A title claiming “under ten minutes” is not a duration measurement.

## Recommend and continue

For links only, stop after sufficient candidates and basic checks. State whether a recommendation uses search information or checked metadata. Neither means the content has been watched.

If matching requires actual content, read a few selected candidates with `--evidence`: transcript for speech, frames for visual conditions. Explain the recommendation using evidence actually opened, with its timestamps and coverage. A failed read means unverified, not irrelevant; do not discard a useful link or claim it was read.

Keep the candidate-to-manifest mapping in the current task. Follow-up questions, clearer frames and saving use that manifest rather than searching again. If no candidates survive filtering, report that outcome and the access limit instead of presenting search-entry URLs as found videos.
