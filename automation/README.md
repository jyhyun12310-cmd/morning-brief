# Automated Instagram cards — no separate paid AI API

Live on main as of 2026-10-01. The owner approved immediate and recurring publication. The successful 7-card preview is run 36860437531; live run 36861877774 published and verified https://www.instagram.com/p/Dd86Xjbm6cq/ on @making_money_for_chicken.

The active Codex heartbeat `미국 주식 7장 카드 자동 게시` (ID 7) starts Tuesday–Saturday at 08:30 Asia/Seoul. It researches one stock, writes a validated Korean seven-card packet, updates automation/inbox/latest.json, and monitors automatic rendering and publication. The local PC and Codex app must be running for the manuscript task; GitHub handles downstream work independently. Holidays and published sessions are skipped.

Use [PACKET_CONTRACT.md](PACKET_CONTRACT.md) for current requirements. The old brief/issue workflows are retired. Do not call separate paid AI APIs. Missing, stale, invalid, or ambiguous packets must never publish. Never delete a reserved publication record or retry an uncertain Instagram operation automatically. Secrets stay in GitHub Secrets and must never enter artifacts.
