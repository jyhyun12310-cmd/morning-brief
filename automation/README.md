# ChatGPT manuscript handoff

This integration uses ChatGPT scheduled tasks to prepare one US stock story with seven cards. GitHub must receive the manuscript and the exact market-data/source snapshot together as one JSON packet. Rendering must not call Claude, OpenAI, or another paid AI API, and must not refetch prices after receiving the packet.

Safety requirements:
- Missing, invalid, stale, or duplicate packets must not publish.
- Preview runs must not invoke Instagram publishing or expose secrets in artifacts.
- Production publishing must keep a persistent deduplication journal and stop on ambiguous publish outcomes.

Permission verification on 2026-09-30: repository reads and creation of the working branch succeeded. A write to a new test workflow was blocked by ChatGPT's security review, before a GitHub permission result was returned. No Instagram post has been made by this verification.
