# /infra — AWS Deployment & Containerization

This directory contains container definitions and AWS infrastructure configurations for deploying ForgeAgent to AWS ECS Fargate.

## Components

- `Dockerfile`: Multi-stage Dockerfile containing Python, OpenCascade (`python-OCP`), CadQuery, and MCP tool servers.
- `copilot/`: AWS Copilot CLI manifest for deploying ECS Fargate orchestrator and public ALB endpoint.
- `s3_storage.py`: S3 artifact manager for storing STEP, STL, glTF, and PNG renders.
