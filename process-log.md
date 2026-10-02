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
