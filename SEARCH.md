# Find videos with Agent Video

The host agent searches for candidates and judges relevance; Agent Video fetches the video materials needed to check the user's conditions.

## Search within the requested platform

Use the user's platform, then the current video task's platform, otherwise YouTube with a brief explanation. Search across platforms only when asked.

Use search tools actually available in the host: platform search or site-scoped web search where suitable. Choose a working alternative if unavailable; no specific search service is required.

| Platform | Useful search path |
|---|---|
| YouTube | Host search or a site-scoped web search for watch / Shorts links |
| Bilibili | Host Bilibili search, including its public video-search API, or a site-scoped web search |
| TikTok | Site-scoped web search for individual videos; try another available search provider if the first returns only topic or shop pages |
| Douyin | Site-scoped web search for individual works; anonymous on-site search may require interactive verification even when individual videos are readable |
| Instagram, X, Reddit, Xiaohongshu, Kuaishou, Weibo | Host platform search or site-scoped web search for individual video posts; public search visibility does not guarantee readable media |
| Vimeo, Dailymotion, TED, Twitch, Pornhub | Host search or site-scoped web search for a single video, talk, clip or completed recording |

Adapt topic keywords when useful, such as `外星人`, `aliens` or `UFO`. Keep queries and candidates small; avoid retrying a blocked search.

## Keep real video candidates

Keep links that identify one video: YouTube watch / Shorts, Bilibili BV / av, TikTok `@user/video/ID`, or Douyin `video/ID` / `modal_id`. Other adapters accept their platform’s single-work links: Instagram reels/posts, X statuses with attached video, native Reddit video posts, Xiaohongshu video notes, Kuaishou works, Weibo posts/TV, Vimeo and Dailymotion videos, TED talks, Twitch clips/completed VODs, and Pornhub viewkeys. Resolve supported share links when necessary. Search pages, topics, shops, channels, profiles and photo posts are not single-video results.

Deduplicate by platform, work ID and selected Bilibili part. Remove irrelevant tracking parameters, but retain access parameters such as Vimeo `h` and Xiaohongshu `xsec_token`; do not guess repairs for malformed links. Keep candidate links and search titles.

## Verify only what the user needs

| User request | Necessary check |
|---|---|
| Find videos about a topic | Search results may suffice for an initial shortlist; say the content has not been read |
| Meet duration or other basic-property conditions | Get necessary metadata with `--get info` |
| Confirm speech or claims | Get and read the relevant `transcript` |
| Confirm demonstrations, UI, code or other visuals | Get and open the relevant `frames` |
| Download a video | Get `video` directly; no summary, transcript or frame check is required first |

Reuse information already sufficient to judge a condition. Leave unverified fields unknown; do not infer spoken language or other unconfirmed facts from titles, descriptions or caption language. When checking duration, use the selected Bilibili part's metadata, not the entire work's search duration.

## Recommend and continue

Stop when enough candidates and evidence support the request. Distinguish search matches, checked metadata, read transcripts and viewed sample frames. Metadata is not content reading; sample frames are not a complete viewing.

Content-based recommendations must use evidence actually opened, with its timestamps and coverage. A failed read means unverified, not irrelevant; do not claim it was read.

Keep each candidate's link and returned manifest in the current task. Follow-ups, clearer frames and saving reuse `--evidence`; without a manifest, download from the link with `--get video`. Do not repeat completed searches or acquisition. If filtering leaves no candidates, report the outcome and access limits, not search-entry URLs.
