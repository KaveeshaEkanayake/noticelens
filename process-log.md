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
