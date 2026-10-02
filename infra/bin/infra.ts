#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { NoticeLensStack } from '../lib/notice-lens-stack';

const app = new cdk.App();

new NoticeLensStack(app, 'NoticeLensStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT ?? '021913935971',
    region:  process.env.CDK_DEFAULT_REGION  ?? 'ap-south-1',
  },
  description: 'NoticeLens - notice analysis pipeline (Textract + Comprehend + Translate)',
});
