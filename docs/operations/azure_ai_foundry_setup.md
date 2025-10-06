---
title: "Azure AI Foundry Setup and Configuration"
version: "1.0.0"
last_updated: "2025-01-27"
owner: "OptiMed AI"
audiences: ["Developers", "DevOps", "SRE"]
---

## Executive Summary

OptiMed uses Azure AI Foundry deployed in the **Data Zone Europe (Sweden Central)** region to provide GDPR-compliant large language model (LLM) services. This document covers setup, configuration, authentication, monitoring, and best practices for Azure AI Foundry integration.

## Overview

### Why Azure AI Foundry?

Azure AI Foundry provides enterprise-grade AI services with critical benefits for healthcare applications:

- **Data Residency**: Data Zone Europe ensures data never leaves EU boundaries
- **GDPR Compliance**: Built-in compliance controls and audit logging
- **Enterprise Security**: Managed identity, VNET integration, private endpoints
- **Performance**: Low-latency access from Azure Container Apps in Sweden Central
- **Reliability**: SLA-backed availability and automatic failover
- **Cost Control**: Per-token pricing with reservation discounts

### Data Zone Europe

Data Zone Europe is a dedicated Azure AI deployment specifically designed for EU data residency requirements:

- **Regional Deployment**: Sweden Central (primary) with North Europe failover
- **Data Sovereignty**: All data processing occurs within EU boundaries
- **Compliance**: GDPR, HIPAA, ISO 27001, SOC 2 certified
- **Audit**: Complete audit trails for regulatory compliance
- **Encryption**: Data encrypted at rest (AES-256) and in transit (TLS 1.3)

---

## Prerequisites

### Azure Resources Required

1. **Azure Subscription** with appropriate permissions
2. **Resource Group** in Sweden Central region
3. **Azure AI Foundry Resource** (created in Data Zone Europe)
4. **Container Apps Environment** (for deployment)
5. **Azure Key Vault** (recommended for secrets management)

### Required Permissions

```bash
# User/Service Principal needs:
- Cognitive Services Contributor (for AI Foundry management)
- Cognitive Services OpenAI User (for API access)
- Key Vault Secrets Officer (if using Key Vault)
```

---

## Azure AI Foundry Resource Creation

### Step 1: Create AI Foundry Resource

```bash
# Set environment variables
export RG="optimed-sweden-rg"
export LOCATION="swedencentral"
export AI_RESOURCE_NAME="optimed-ai-sweden"

# Create Azure OpenAI resource in Data Zone Europe
az cognitiveservices account create \
  --name $AI_RESOURCE_NAME \
  --resource-group $RG \
  --location $LOCATION \
  --kind OpenAI \
  --sku S0 \
  --custom-domain $AI_RESOURCE_NAME \
  --assign-identity \
  --public-network-access Disabled  # Use private endpoint for production
```

### Step 2: Deploy Models

OptiMed uses GPT-4o for clinical information retrieval:

```bash
# Deploy GPT-4o model
az cognitiveservices account deployment create \
  --resource-group $RG \
  --name $AI_RESOURCE_NAME \
  --deployment-name gpt-4o \
  --model-name gpt-4o \
  --model-version "2024-08-06" \
  --model-format OpenAI \
  --sku-capacity 50 \
  --sku-name "Standard"

# Verify deployment
az cognitiveservices account deployment show \
  --resource-group $RG \
  --name $AI_RESOURCE_NAME \
  --deployment-name gpt-4o
```

### Step 3: Configure Networking

For production, use private endpoints to ensure traffic stays within Azure:

```bash
# Create private endpoint
az network private-endpoint create \
  --name $AI_RESOURCE_NAME-pe \
  --resource-group $RG \
  --vnet-name optimed-vnet \
  --subnet optimed-subnet \
  --private-connection-resource-id $(az cognitiveservices account show \
    --name $AI_RESOURCE_NAME \
    --resource-group $RG \
    --query id -o tsv) \
  --group-id account \
  --connection-name $AI_RESOURCE_NAME-connection
```

---

## Authentication Configuration

### Method 1: API Key Authentication (Development)

```bash
# Retrieve API keys
az cognitiveservices account keys list \
  --resource-group $RG \
  --name $AI_RESOURCE_NAME

# Output:
# {
#   "key1": "abc123...",
#   "key2": "def456..."
# }

# Store in environment variables
export AZURE_OPENAI_API_KEY="abc123..."
export AZURE_OPENAI_ENDPOINT="https://optimed-ai-sweden.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
export AZURE_OPENAI_API_VERSION="2024-08-01-preview"
```

### Method 2: Managed Identity (Production - Recommended)

```bash
# Enable managed identity for Container App
az containerapp identity assign \
  --name optimed-api-sweden \
  --resource-group $RG \
  --system-assigned

# Get the managed identity principal ID
PRINCIPAL_ID=$(az containerapp identity show \
  --name optimed-api-sweden \
  --resource-group $RG \
  --query principalId -o tsv)

# Assign Cognitive Services OpenAI User role
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Cognitive Services OpenAI User" \
  --scope $(az cognitiveservices account show \
    --name $AI_RESOURCE_NAME \
    --resource-group $RG \
    --query id -o tsv)
```

**Managed Identity Configuration in Code**:

```python
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

# Use managed identity (no API key needed)
credential = DefaultAzureCredential()
token = credential.get_token("https://cognitiveservices.azure.com/.default")

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_ad_token=token.token,
    api_version="2024-08-01-preview"
)
```

### Method 3: Azure Key Vault (Production Alternative)

```bash
# Store API key in Key Vault
az keyvault secret set \
  --vault-name optimed-keyvault \
  --name azure-openai-api-key \
  --value "abc123..."

# Grant Container App access to Key Vault
az keyvault set-policy \
  --name optimed-keyvault \
  --object-id $PRINCIPAL_ID \
  --secret-permissions get list
```

**Key Vault Configuration in Container Apps**:

```bash
# Configure Container App to use Key Vault secret
az containerapp secret set \
  --name optimed-api-sweden \
  --resource-group $RG \
  --secrets azure-openai-api-key=keyvaultref:https://optimed-keyvault.vault.azure.net/secrets/azure-openai-api-key,identityref:system

# Reference in environment variables
az containerapp update \
  --name optimed-api-sweden \
  --resource-group $RG \
  --set-env-vars AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key
```

---

## Environment Configuration

### Backend Environment Variables

Complete configuration for OptiMed backend:

```bash
# Azure AI Foundry Configuration
AZURE_OPENAI_ENDPOINT="https://optimed-ai-sweden.openai.azure.com/"
AZURE_OPENAI_API_KEY="<api-key-or-use-managed-identity>"
AZURE_OPENAI_DEPLOYMENT="gpt-4o"
AZURE_OPENAI_API_VERSION="2024-08-01-preview"

# Alternative: Use managed identity (set this to enable)
USE_AZURE_MANAGED_IDENTITY="true"

# Model Configuration
LLM_MODEL="gpt-4o"
LLM_TEMPERATURE="0.1"
LLM_MAX_TOKENS="4096"
LLM_STREAMING="true"

# Rate Limiting
AZURE_OPENAI_MAX_RETRIES="3"
AZURE_OPENAI_RETRY_DELAY="2"
AZURE_OPENAI_TIMEOUT="60"
```

### Container Apps Deployment

```bash
# Deploy with Azure AI Foundry configuration
az containerapp update \
  --name optimed-api-sweden \
  --resource-group $RG \
  --set-env-vars \
    AZURE_OPENAI_ENDPOINT="https://optimed-ai-sweden.openai.azure.com/" \
    AZURE_OPENAI_DEPLOYMENT="gpt-4o" \
    AZURE_OPENAI_API_VERSION="2024-08-01-preview" \
    USE_AZURE_MANAGED_IDENTITY="true" \
    LLM_MODEL="gpt-4o" \
    LLM_TEMPERATURE="0.1" \
    LLM_MAX_TOKENS="4096"
```

---

## Code Integration

### LLM Client Configuration

OptiMed uses the `openai` Python library with Azure endpoint:

```python
# src/optimed/adapters/openai_gpt/client.py
import os
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential

class AzureOpenAIClient:
    """Azure AI Foundry client wrapper."""

    def __init__(self):
        use_managed_identity = os.getenv("USE_AZURE_MANAGED_IDENTITY", "false").lower() == "true"

        if use_managed_identity:
            # Use managed identity
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")

            self.client = AzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                azure_ad_token=token.token,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
            )
        else:
            # Use API key
            self.client = AzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
            )

        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    async def chat_completion(self, messages, temperature=0.1, max_tokens=4096, stream=False):
        """Send chat completion request."""
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream
        )
        return response
```

### Streaming Support

```python
async def stream_chat_completion(self, messages):
    """Stream chat completion for real-time responses."""
    stream = self.client.chat.completions.create(
        model=self.deployment,
        messages=messages,
        temperature=0.1,
        stream=True
    )

    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

---

## Monitoring and Observability

### Azure Monitor Integration

```bash
# Enable diagnostic settings for Azure AI Foundry
az monitor diagnostic-settings create \
  --name optimed-ai-diagnostics \
  --resource $(az cognitiveservices account show \
    --name $AI_RESOURCE_NAME \
    --resource-group $RG \
    --query id -o tsv) \
  --logs '[{"category": "RequestResponse", "enabled": true}, {"category": "Audit", "enabled": true}]' \
  --metrics '[{"category": "AllMetrics", "enabled": true}]' \
  --workspace $(az monitor log-analytics workspace show \
    --resource-group $RG \
    --workspace-name optimed-logs \
    --query id -o tsv)
```

### Key Metrics to Monitor

1. **Request Metrics**
   - Total requests
   - Successful requests
   - Failed requests
   - Request latency (p50, p95, p99)

2. **Token Metrics**
   - Prompt tokens consumed
   - Completion tokens generated
   - Total tokens per minute
   - Token quota utilization

3. **Performance Metrics**
   - Time to first token (TTFT)
   - Tokens per second (TPS)
   - End-to-end latency

4. **Error Metrics**
   - Rate limit errors (429)
   - Authentication errors (401)
   - Service errors (500)

### Kusto Query Examples

```kql
// Request volume over time
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| where Category == "RequestResponse"
| summarize RequestCount = count() by bin(TimeGenerated, 5m)
| render timechart

// Token consumption analysis
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| where Category == "RequestResponse"
| extend PromptTokens = toint(parse_json(properties_s).usage.prompt_tokens)
| extend CompletionTokens = toint(parse_json(properties_s).usage.completion_tokens)
| summarize
    TotalPromptTokens = sum(PromptTokens),
    TotalCompletionTokens = sum(CompletionTokens),
    AvgPromptTokens = avg(PromptTokens),
    AvgCompletionTokens = avg(CompletionTokens)
by bin(TimeGenerated, 1h)

// Error rate monitoring
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| where Category == "RequestResponse"
| extend StatusCode = toint(resultSignature_d)
| summarize
    TotalRequests = count(),
    ErrorCount = countif(StatusCode >= 400),
    ErrorRate = 100.0 * countif(StatusCode >= 400) / count()
by bin(TimeGenerated, 5m)
| where ErrorRate > 5  // Alert if error rate > 5%
```

### Application Insights Integration

```python
from applicationinsights import TelemetryClient
import logging

# Initialize Application Insights
tc = TelemetryClient(os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"))

async def chat_completion_with_telemetry(messages):
    """Track LLM calls in Application Insights."""
    start_time = time.time()

    try:
        response = await client.chat_completion(messages)

        # Track success
        tc.track_event("LLM_Request", {
            "deployment": client.deployment,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "duration_ms": (time.time() - start_time) * 1000
        })

        return response
    except Exception as e:
        # Track failure
        tc.track_exception()
        tc.track_event("LLM_Request_Failed", {
            "error": str(e),
            "duration_ms": (time.time() - start_time) * 1000
        })
        raise
```

---

## Rate Limiting and Quotas

### Token Quota Management

Azure AI Foundry uses **Tokens Per Minute (TPM)** quotas:

```python
# Production configuration
DEFAULT_QUOTA = {
    "gpt-4o": {
        "tpm": 50000,  # 50K tokens per minute
        "rpm": 500,    # 500 requests per minute
        "daily_limit": 72_000_000  # 72M tokens per day
    }
}
```

### Implementing Rate Limiting

```python
import asyncio
from collections import deque
import time

class RateLimiter:
    """Token-based rate limiter for Azure AI Foundry."""

    def __init__(self, tpm: int = 50000, rpm: int = 500):
        self.tpm = tpm
        self.rpm = rpm
        self.token_window = deque()
        self.request_window = deque()
        self.window_size = 60  # 1 minute window

    async def acquire(self, tokens: int):
        """Wait if necessary to stay within rate limits."""
        now = time.time()

        # Remove old entries
        cutoff = now - self.window_size
        while self.token_window and self.token_window[0][0] < cutoff:
            self.token_window.popleft()
        while self.request_window and self.request_window[0] < cutoff:
            self.request_window.popleft()

        # Check if we're within limits
        current_tokens = sum(t for _, t in self.token_window)
        current_requests = len(self.request_window)

        if current_tokens + tokens > self.tpm or current_requests >= self.rpm:
            # Calculate wait time
            if self.token_window:
                wait_time = self.window_size - (now - self.token_window[0][0])
            else:
                wait_time = 1

            logging.info(f"Rate limit approaching, waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
            return await self.acquire(tokens)  # Recursive retry

        # Record this request
        self.token_window.append((now, tokens))
        self.request_window.append(now)

# Usage
rate_limiter = RateLimiter(tpm=50000, rpm=500)

async def rate_limited_completion(messages):
    # Estimate tokens (rough approximation)
    estimated_tokens = sum(len(m["content"]) // 4 for m in messages) + 1000

    await rate_limiter.acquire(estimated_tokens)
    return await client.chat_completion(messages)
```

### Handling 429 Errors

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry_error_callback=lambda retry_state: None
)
async def completion_with_retry(messages):
    """Automatic retry with exponential backoff for rate limit errors."""
    try:
        return await client.chat_completion(messages)
    except openai.RateLimitError as e:
        logging.warning(f"Rate limit hit: {e}. Retrying...")
        raise  # Trigger retry
    except Exception as e:
        logging.error(f"Unretryable error: {e}")
        raise
```

---

## Cost Optimization

### Token Usage Optimization

```python
# Optimize prompts to reduce token consumption
def optimize_prompt(prompt: str, max_length: int = 1000) -> str:
    """Truncate or summarize prompts to reduce token usage."""
    if len(prompt) <= max_length:
        return prompt

    # Truncate with ellipsis
    return prompt[:max_length-3] + "..."

# Use lower temperature for deterministic tasks
response = await client.chat_completion(
    messages,
    temperature=0.0,  # Deterministic, often sufficient
    max_tokens=1024   # Limit response length
)
```

### Reserved Capacity

For predictable workloads, purchase reserved capacity:

```bash
# Reserved capacity provides significant discounts (up to 50%)
# Purchase through Azure Portal: Cognitive Services > Reservations
# Commitment tiers: 100K, 300K, 1M, 3M tokens/month
```

### Cost Monitoring

```kql
// Daily cost estimation (GPT-4o pricing: $0.005/1K prompt tokens, $0.015/1K completion tokens)
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| extend PromptTokens = toint(parse_json(properties_s).usage.prompt_tokens)
| extend CompletionTokens = toint(parse_json(properties_s).usage.completion_tokens)
| summarize
    TotalPromptTokens = sum(PromptTokens),
    TotalCompletionTokens = sum(CompletionTokens)
by bin(TimeGenerated, 1d)
| extend EstimatedCost = (TotalPromptTokens / 1000.0 * 0.005) + (TotalCompletionTokens / 1000.0 * 0.015)
| project TimeGenerated, TotalPromptTokens, TotalCompletionTokens, EstimatedCost
```

---

## Security Best Practices

### 1. Use Managed Identity

✅ **DO**: Use managed identity in production
❌ **DON'T**: Store API keys in code or environment variables

### 2. Enable Private Endpoints

✅ **DO**: Use private endpoints for production
❌ **DON'T**: Expose AI Foundry to public internet

### 3. Implement Audit Logging

✅ **DO**: Enable diagnostic settings and log all requests
❌ **DON'T**: Disable logging to save costs

### 4. Rotate API Keys Regularly

✅ **DO**: Rotate keys every 90 days if using key-based auth
❌ **DON'T**: Use the same key indefinitely

### 5. Monitor for Anomalies

✅ **DO**: Set up alerts for unusual usage patterns
❌ **DON'T**: Ignore suspicious activity

---

## Troubleshooting

### Common Issues

#### Issue 1: Authentication Failures

**Symptoms**: 401 Unauthorized errors

**Solutions**:
```bash
# Check API key validity
az cognitiveservices account keys list \
  --resource-group $RG \
  --name $AI_RESOURCE_NAME

# Verify managed identity has correct role
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --all
```

#### Issue 2: Rate Limit Errors (429)

**Symptoms**: "Rate limit exceeded" errors

**Solutions**:
- Implement exponential backoff with retries
- Increase quota through Azure portal
- Optimize prompts to reduce token usage
- Consider deploying multiple model instances

#### Issue 3: High Latency

**Symptoms**: Slow response times (>5s)

**Solutions**:
- Check network latency between Container Apps and AI Foundry
- Use streaming for perceived performance improvement
- Optimize prompt length
- Consider response caching for common queries

#### Issue 4: Model Not Available

**Symptoms**: "Deployment not found" errors

**Solutions**:
```bash
# List available deployments
az cognitiveservices account deployment list \
  --resource-group $RG \
  --name $AI_RESOURCE_NAME

# Verify deployment status
az cognitiveservices account deployment show \
  --resource-group $RG \
  --name $AI_RESOURCE_NAME \
  --deployment-name gpt-4o
```

---

## Compliance and Governance

### GDPR Compliance

Azure AI Foundry in Data Zone Europe provides:

1. **Data Residency**: All data stays within EU
2. **Data Processing Agreement**: Available through Azure portal
3. **Audit Logs**: Complete request/response logging
4. **Right to Erasure**: Data retention policies configurable
5. **Data Portability**: Export capabilities via API

### Audit Requirements

```kql
// Complete audit trail for compliance
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
| where Category == "Audit"
| project
    TimeGenerated,
    OperationName,
    CallerIpAddress,
    CorrelationId,
    ResourceId,
    ResultSignature
| order by TimeGenerated desc
```

---

## Conclusion

Azure AI Foundry in Data Zone Europe provides OptiMed with enterprise-grade LLM capabilities while ensuring GDPR compliance and EU data residency. By following the configuration and best practices outlined in this guide, you can deploy and maintain a secure, performant, and cost-effective AI infrastructure for clinical applications.

### Key Takeaways

- **Use managed identity** for authentication in production
- **Enable private endpoints** to keep traffic within Azure
- **Monitor token usage** to optimize costs
- **Implement rate limiting** to stay within quotas
- **Enable comprehensive logging** for compliance and debugging
- **Test failover scenarios** to ensure reliability
- **Review security** settings regularly

For additional support, consult:
- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-services/openai/)
- [Data Zone Europe Guide](https://learn.microsoft.com/azure/ai-services/openai/concepts/data-zones)
- [GDPR Compliance](https://learn.microsoft.com/azure/compliance/gdpr)
