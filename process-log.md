# Process Log

Chronological record of setup steps, decisions, and blockers for the NoticeLens project.

---

## Sep 23, 2026

- Created AWS account (root user, email/password sign-up).
- Set up billing budget alert to monitor spend.
- Submitted Amazon Bedrock use-case request for model access.
- Quota status: Bedrock TPM quotas currently blocked at 0 — awaiting approval.

## Sep 24, 2026

- Installed Kiro IDE.
- Set up AWS Agent Toolkit:
  - Installed `uv` and AWS CLI v2.
  - Authenticated via `aws login` (browser flow), profile `noticelens`, region `ap-south-1`.
  - Ran `aws configure agent-toolkit` — installed 24 default AWS skills for Kiro, Claude Code, and Cursor.
  - Configured `AWS_MCP_PROXY_PROFILES: noticelens` in `~/.kiro/settings/mcp.json`.
  - Added AWS advanced rules to `.kiro/steering/aws-agent-rules.md`.
- Verified setup with `aws ec2 describe-regions` — returned all 34 available regions.
- Initialised GitHub repo and made first commit.

## Sep 25 – Oct 2, 2026

- Tested AWS service availability in ap-south-1:
  - Amazon Translate (EN to Sinhala): working
  - Amazon Comprehend (detect-entities): working
  - Amazon Textract (detect-document-text): working
  - Amazon Bedrock: unavailable (quotas blocked at 0 TPM, use-case pending)
- Decided on Textract + Comprehend + Translate pipeline (no Bedrock for now).
- Built NoticeLens full-stack:
  - Frontend: static SPA (S3 + CloudFront with OAC)
  - Backend: API Gateway (POST /analyse, 10 req/s throttle, 2 MB limit) + Lambda (Python 3.12, 512 MB, 30s timeout)
  - Pipeline: Textract detect-document-text → Comprehend detect-entities → pattern matching → optional Translate to Sinhala
  - Every extracted item carries a Textract bounding box for UI highlighting
  - Low-confidence items isolated under "Needs verification", never stated as fact
- Infrastructure as code: AWS CDK (TypeScript) under infra/
- First deploy attempt failed: API GW stage logging requires a CloudWatch Logs role registered at the account level. Fixed by adding an AwsCustomResource to call updateAccount before stage creation.
- CDK bootstrap completed for ap-south-1.
- Stack deployed successfully (NoticeLensStack).

### Live endpoints
- Frontend: https://do41dacharqdc.cloudfront.net
- API: https://71xvl8tqp6.execute-api.ap-south-1.amazonaws.com/prod/analyse
- CloudFront distribution ID: E3NFSD7E5ALCUP

## Oct 2–3, 2026 — final build session

- **Fixed source highlighting (core feature was broken).** Deadlines, fees, documents
  and verify rows emitted bounding boxes via `JSON.stringify` inside a double-quoted
  `onclick` attribute. The JSON's own double quotes closed the attribute early, which
  produced repeated `Uncaught SyntaxError: Unexpected end of input` and meant those
  handlers never registered. Moved to single-quoted `data-bbox` attributes and made
  `selectItem` read the attribute when no bbox argument is passed. Only the checklist
  had worked, because it alone read the attribute itself.
- **Fixed translation misalignment.** Strings were joined with a `||NL||` sentinel,
  sent to Translate in one call, then split on the sentinel. Translate does not preserve
  such a marker reliably: it leaked into visible Sinhala text and translations landed on
  the wrong items. Replaced with one call per string, issued in parallel, so each
  translation is bound to its own index.
- **Extraction quality:** checklist items now join continuation lines so sentences
  complete; lead-in clauses ending in a colon are dropped; overlapping checklist entries
  deduplicated; deadlines deduplicated by meaning (computed interval or date) rather
  than by source line, which had allowed "within 14 days" to appear three times.
- **Interface:** rebuilt the visual design around a single rule — amber marks evidence
  and nothing else, matching the highlight drawn on the document. Public Sans for the
  interface (a typeface designed for public-sector communication) and Noto Sans Sinhala
  for Sinhala. Document panel made sticky so evidence stays visible while scrolling
  findings.
- **First impression:** the page now runs a sample through the real pipeline on load,
  so it is never empty, and a four-step guided tour explains the verification flow.
- Verified before each deploy: inline script extracted and checked with `node --check`,
  Lambda checked with `ast.parse`.

### Known issues at submission
- Fee amounts are extracted correctly but not labelled with their table row.
- Fees are deduplicated by amount, so two different charges of the same value collapse.
- Document detection relies on a keyword list and will miss unusual document names.
