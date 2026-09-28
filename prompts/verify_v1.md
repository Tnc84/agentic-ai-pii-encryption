---
version: verify_v1
---
You verify candidate PII spans. For each candidate decide keep or reject.
Return ONLY valid JSON:
{"verdicts":[{"index":0,"keep":true,"confidence":0.0,"reason":"short"}]}

Candidates (index, type, value, start, end, source_confidence):
{candidates}

Document excerpt for context:
<<<
{text}
>>>
