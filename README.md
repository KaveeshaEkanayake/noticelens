# NoticeLens

**Live: https://do41dacharqdc.cloudfront.net** · Built for the AWS Builder Center *Zero to Shipped* hackathon.

An official letter can be perfectly clear and still leave you unsure what to do. NoticeLens reads a notice — a bank letter, a university circular, a utility bill — and sets out the deadlines, fees, documents and steps it requires. Select any one of them and it highlights the exact line on the page it came from.

No sign-in. Three sample notices are built in, so you can see it work without uploading anything.

## The idea: every claim is traceable

Document summarisers are common. The problem with them is that you have to trust the summary.

NoticeLens never asserts anything it can't point at. Each extracted fact carries the Textract bounding box of the line it came from, so selecting a finding draws a box over that region of the original image. Verification is a coordinate on the page, not a model's say-so.

Anything the pipeline is unsure about goes under **Needs verification** rather than being stated as fact. A tool that says "I'm not certain about this date" is more useful than one that invents a confident answer.

## How it works

```
Browser (S3 + CloudFront)
        │  image, base64, ≤2 MB
        ▼
API Gateway  (POST /analyse · 10 req/s · 20 burst)
        ▼
Lambda  (Python 3.12 · 512 MB · 30s)
        │
        ├── Amazon Textract      detect_document_text → lines + geometry
        ├── Amazon Comprehend    detect_entities → DATE, QUANTITY, ORGANIZATION
        ├── Classification       deadline vs. cited date vs. document date
        └── Amazon Translate     English → Sinhala (optional)
        ▼
    Findings, each carrying its source line and bounding box
```

Extraction is deliberately rule-based over entity detection rather than generative. Dates are classified before being called deadlines: a date in the past, or one next to "Gazette", "Act No" or "dated", is a citation, not something you have to act on. Relative deadlines such as "within 14 days" are computed from the document's own date and marked **Inferred**.

## Built with an AI coding agent connected to AWS

Kiro, connected through the **Agent Toolkit for AWS** (AWS MCP Server plus AWS skills), using a dedicated `noticelens` CLI profile in `ap-south-1`.

Evidence in [`docs/agent-setup/`](docs/agent-setup/):

| File | What it shows |
|---|---|
| `01-kiro-installed.png` | Kiro installed and signed in |
| `02-agent-toolkit-setup.png` | Setup prompt issued from the AWS Console |
| `03-agent-connected.png` | AWS sign-in completed for the agent |
| `04-agent-aws-call.png` | `aws ec2 describe-regions` run by the agent, returning live account data |
| `05-toolkit-complete.png` | All 8 setup steps complete — CLI, profile, MCP config, 24 AWS skills |

The agent provisioned the CDK stack, wrote the Lambda pipeline and the frontend, and ran deployments against the account. [`process-log.md`](process-log.md) is the dated record.

## Running it

```bash
cd infra
npm install
cdk deploy --profile <your-profile> --require-approval never
```

Outputs the CloudFront URL and the API endpoint. The Lambda needs `textract:DetectDocumentText`, `comprehend:DetectEntities` and `translate:TranslateText`; the CDK stack grants exactly those and nothing more.

## Limits, stated plainly

- **English documents only.** Amazon Textract does not read Sinhala script, so input must be English. Output is translated to Sinhala, which is where most of the value sits for Sri Lankan readers.
- **Single page.** Uses the synchronous Textract API, so multi-page PDFs are not supported.
- **Rules, not reasoning.** Extraction is pattern matching over detected entities. It handles the common shapes of official correspondence well and will miss unusual phrasing.
- **Fee labels.** Amounts are extracted correctly but not yet labelled with their table row ("Arrears", "Total amount due").
- Uploaded images are passed to AWS services and are not stored.

## Repository

```
frontend/index.html       the whole UI — markup, styles, logic, no build step
frontend/samples/         three sample notices
infra/lib/                CDK stack: S3, CloudFront + OAC, API Gateway, Lambda, IAM
infra/lambda/index.py     the analysis pipeline
docs/agent-setup/         agent connection evidence
process-log.md            dated build log
```

## Licence

MIT
