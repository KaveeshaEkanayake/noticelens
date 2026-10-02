import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as path from 'path';

export class NoticeLensStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ── Lambda: analysis pipeline ───────────────────────────────────────
    const analysisRole = new iam.Role(this, 'AnalysisLambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Least-privilege grants for Textract, Comprehend, Translate
    analysisRole.addToPolicy(new iam.PolicyStatement({
      sid: 'TextractDetect',
      actions: ['textract:DetectDocumentText'],
      resources: ['*'],
    }));
    analysisRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ComprehendDetect',
      actions: ['comprehend:DetectEntities'],
      resources: ['*'],
    }));
    analysisRole.addToPolicy(new iam.PolicyStatement({
      sid: 'TranslateText',
      actions: ['translate:TranslateText'],
      resources: ['*'],
    }));

    const analysisLogGroup = new logs.LogGroup(this, 'AnalysisLambdaLogs', {
      logGroupName: '/aws/lambda/noticelens-analysis',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const analysisLambda = new lambda.Function(this, 'AnalysisLambda', {
      functionName: 'noticelens-analysis',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda')),
      role: analysisRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      logGroup: analysisLogGroup,
      environment: {
        POWERTOOLS_SERVICE_NAME: 'noticelens',
      },
    });

    // ── API Gateway account-level CloudWatch Logs role ──────────────────
    // Required once per account per region before any stage can enable logging.
    const apiGwCwRole = new iam.Role(this, 'ApiGwCloudWatchRole', {
      assumedBy: new iam.ServicePrincipal('apigateway.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonAPIGatewayPushToCloudWatchLogs'),
      ],
    });

    // Register it at the account level via a custom resource
    const apiGwAccount = new cr.AwsCustomResource(this, 'ApiGwAccount', {
      onCreate: {
        service: 'APIGateway',
        action: 'updateAccount',
        parameters: {
          patchOperations: [{
            op: 'replace',
            path: '/cloudwatchRoleArn',
            value: apiGwCwRole.roleArn,
          }],
        },
        physicalResourceId: cr.PhysicalResourceId.of('ApiGwAccount'),
      },
      onUpdate: {
        service: 'APIGateway',
        action: 'updateAccount',
        parameters: {
          patchOperations: [{
            op: 'replace',
            path: '/cloudwatchRoleArn',
            value: apiGwCwRole.roleArn,
          }],
        },
        physicalResourceId: cr.PhysicalResourceId.of('ApiGwAccount'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['apigateway:PATCH'],
          resources: ['arn:aws:apigateway:*::/account'],
        }),
        new iam.PolicyStatement({
          actions: ['iam:PassRole'],
          resources: [apiGwCwRole.roleArn],
        }),
      ]),
    });

    // ── API Gateway ─────────────────────────────────────────────────────
    const api = new apigw.RestApi(this, 'NoticeLensApi', {
      restApiName: 'noticelens-api',
      description: 'NoticeLens analysis API',
      binaryMediaTypes: ['image/png', 'image/jpeg', 'application/pdf', 'multipart/form-data'],
      minCompressionSize: cdk.Size.bytes(0),
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: apigw.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'X-Amz-Date', 'Authorization'],
      },
      deployOptions: {
        stageName: 'prod',
        throttlingRateLimit: 10,   // 10 req/s steady
        throttlingBurstLimit: 20,  // 20 req burst
        loggingLevel: apigw.MethodLoggingLevel.ERROR,
      },
      // Don't let CDK create a second CloudWatch role — we manage it above
      cloudWatchRole: false,
    });

    // Ensure the account-level CW role is registered before the stage
    api.node.addDependency(apiGwAccount);

    // POST /analyse
    const analyseResource = api.root.addResource('analyse');
    const lambdaIntegration = new apigw.LambdaIntegration(analysisLambda, {
      proxy: true,
    });
    analyseResource.addMethod('POST', lambdaIntegration, {
      requestParameters: {},
      // Enforce 2 MB limit via a request validator on content-length is not
      // natively available in REST API; limit is enforced in Lambda as well.
    });

    // ── S3: frontend bucket ─────────────────────────────────────────────
    const frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `noticelens-frontend-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
    });

    // ── CloudFront OAC ──────────────────────────────────────────────────
    const oac = new cloudfront.S3OriginAccessControl(this, 'FrontendOAC', {
      description: 'OAC for NoticeLens frontend bucket',
    });

    const distribution = new cloudfront.Distribution(this, 'FrontendDistribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket, {
          originAccessControl: oac,
        }),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        compress: true,
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
        },
      ],
      comment: 'NoticeLens frontend',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_ALL,
    });

    // ── Deploy frontend to S3 ───────────────────────────────────────────
    new s3deploy.BucketDeployment(this, 'DeployFrontend', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '../../frontend'))],
      destinationBucket: frontendBucket,
      distribution,
      distributionPaths: ['/*'],
    });

    // ── Outputs ──────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'CloudFrontUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'NoticeLens public URL',
      exportName: 'NoticeLensUrl',
    });

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: `${api.url}analyse`,
      description: 'NoticeLens API endpoint',
      exportName: 'NoticeLensApiUrl',
    });

    new cdk.CfnOutput(this, 'DistributionId', {
      value: distribution.distributionId,
      description: 'CloudFront distribution ID',
    });
  }
}
