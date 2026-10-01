# Automated Instagram cards — no separate paid AI API

Live on main as of 2026-10-01. The owner approved immediate and recurring publication. The successful 7-card preview is run 36860437531; live run 36861877774 published and verified https://www.instagram.com/p/Dd86Xjbm6cq/ on @making_money_for_chicken.

The active ChatGPT Work cloud task `미국주식 7장 클라우드 자동게시` (ID `6abe558092a081918e9ecc4fb326252d`, conversation `6abe54a7-2420-83e8-b396-9bda1f7327f5`) is scheduled Tuesday–Saturday at 08:30 Asia/Seoul starting 2026-10-02. It researches one stock, writes a validated Korean seven-card packet, updates automation/inbox/latest.json, and monitors automatic rendering and publication. No local PC or app is needed. The former local heartbeat ID 7 is paused. Cloud GitHub reads and duplicate skipping were verified; the first scheduled execution has not yet occurred, and the server next_run_time was null at setup. Holidays and published sessions are skipped.

Follow [EDITORIAL_GUIDE.md](EDITORIAL_GUIDE.md) for concise Korean storytelling and the Gmarket Sans/Pretendard typography. The historical sample in automation/examples is preview-only; select design_preview in a manual card-packet run to render it without posting.

Use [PACKET_CONTRACT.md](PACKET_CONTRACT.md) for current requirements. The old brief/issue workflows are retired. Do not call separate paid AI APIs. Missing, stale, invalid, or ambiguous packets must never publish. Never delete a reserved publication record or retry an uncertain Instagram operation automatically. Secrets stay in GitHub Secrets and must never enter artifacts.
