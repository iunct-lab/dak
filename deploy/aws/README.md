# deploy/aws — DAK on Lambda

`template.yaml` deploys DAK as a Lambda function (`docs/architecture/serverless.md`, S1);
`dev-caller.yaml` is a stand-in caller for checking it in dev. Nothing here contains an
account, a role name or a key: they are parameters.

## What it makes

- `DakFunction`: the image from `agent/Dockerfile.lambda`, arm64, 1536 MB, 900 s, with
  `MaximumRetryAttempts: 0` (an automatic retry would bill the LLM call again),
  `ReservedConcurrency` (default 2) and the per-turn limits `DAK_MAX_LLM_CALLS` /
  `DAK_MAX_OUTPUT_TOKENS` / `DAK_MAX_TURN_SECONDS` (#134).
- `JobTable`: on-demand DynamoDB, keys `pk` / `sk`, TTL `expires_at`.
- `AWS::Lambda::Permission` for `CallerRoleArn` (and `SecondCallerRoleArn`): only these roles
  may `lambda:InvokeFunction`. Developers are not allowed on DAK; they assume the caller's role.
  How a caller calls the function (streaming, request and result shapes, its own MCP server,
  the IAM steps) is in `docs/architecture/serverless.md`, "呼び出し元との契約（#837）".
- `Budget`: monthly `BudgetLimitUsd` (default 10), notified at 50% and 100% of the actual cost.
  It covers the whole account unless you add a cost filter.

## Build and deploy

Approval: a dev deploy (`sam deploy`, executing a change set) costs money, so its approval is
taken once, when the PBI is made Ready, in the PBI's `## 回答` with an upper limit in USD. The
Task's step 1 does not ask again. If the work is expected to go over that limit, stop before
deploying and ask again in the PBI. Cleaning up (`sam delete`, below) needs no approval.

```bash
docker buildx build --platform linux/arm64 -f agent/Dockerfile.lambda -t <repo>:<tag> agent
# push to your ECR repository, then:
sam validate --lint -t deploy/aws/template.yaml
sam deploy -t deploy/aws/template.yaml --stack-name <name> --capabilities CAPABILITY_IAM \
  --parameter-overrides ImageUri=<ecr uri> ModelName=<litellm model id> \
    BedrockModelArns=<arn,arn> CallerRoleArn=<role arn> BudgetEmail=<address>
```

To call Anthropic's API instead of Bedrock, leave `BedrockModelArns` empty and pass
`ApiKeyParameterName=<SSM parameter name>` (a SecureString). Only the *name* is given: the function
reads that one parameter at its first call (`ssm:GetParameter`) and puts the value in
`ANTHROPIC_API_KEY`. The value is in no template, image or log.

For a dev check, deploy `dev-caller.yaml` as well (it needs `--capabilities CAPABILITY_IAM`):

```bash
sam deploy -t deploy/aws/dev-caller.yaml --stack-name <name> --capabilities CAPABILITY_IAM \
  --parameter-overrides DakFunctionArn=<arn> DeveloperPrincipalArn=<arn>
```

The roles and the function ARN depend on each other, so: deploy the DAK stack with a role you
already have as `CallerRoleArn`, deploy `dev-caller.yaml` with the DAK function's ARN
(`DeveloperPrincipalArn` is who may assume the roles), then update the DAK stack with the
`CallerRoleArn` output.

An async call that is throttled by `ReservedConcurrency` is dropped after 60 s (`MaximumEventAgeInSeconds`),
so it is not run later; polling it returns `not_found`.

## Call it

```bash
# start (async); the result is read with op=get
aws lambda invoke --invocation-type Event --function-name <arn> \
  --cli-binary-format raw-in-base64-out \
  --payload '{"message": "...", "job_id": "<unique id>"}' /dev/null
aws lambda invoke --function-name <arn> --cli-binary-format raw-in-base64-out \
  --payload '{"op": "get", "job_id": "<unique id>"}' out.json
```

Questions and answers need Enforcer Mode: deploy with `EnforcerMode=true` (default `false`, it
sets `ENABLE_ENFORCER_MODE`) to get the `ask_question` and `attempt_answer` tools. Enforcer Mode
refuses a text-only reply, so put both in `dak:tools` (`"state_delta": {"dak:tools":
["ask_question", "attempt_answer"]}`); they are not added for you. A turn that ends with
`attempt_answer` returns its `answer` as `output`. A question comes back as `"status": "waiting"`
with `pending` and is answered with `{"op": "reply", "session_id", "approval_id", "answer"}`
(`docs/architecture/serverless.md`).

## Clean up

`sam delete --stack-name <name>` for both stacks.
