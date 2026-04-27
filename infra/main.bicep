// EDGAR — Azure Container Apps infrastructure
// Resource group: rg-lpa-edgar-sandbox-germanywestcentral
//
// Resources deployed:
//   - User-assigned managed identity  (id-lpa-edgar-sandbox)
//   - Azure Container Registry         (crlpaedgarsandbox)
//   - Azure Key Vault                  (kv-lpa-edgar-sbx)
//   - Log Analytics workspace          (log-lpa-edgar-sandbox)
//   - Container Apps Environment       (cae-lpa-edgar-sandbox)
//   - Backend Container App            (ca-edgar-backend)  — internal ingress
//   - Frontend Container App           (ca-edgar-frontend) — external ingress
//   - Storage account for AI Foundry   (stlpaedgarai)
//   - Azure AI Foundry Hub             (aih-lpa-edgar-sandbox)
//   - Azure AI Foundry Project         (aip-lpa-edgar-sandbox)
//   - Qwen-32b serverless endpoint     (qwen32b)
//
// Role assignments are NOT created here (requires Owner on the RG).
// Run infra/assign-roles.sh once after first deployment to set them up.
//
// NOTE: Data is ephemeral in this sandbox configuration (SQLite lives in the
// container). Add an Azure Files mount before promoting to production.

targetScope = 'resourceGroup'

param location string = resourceGroup().location

// ── Names ─────────────────────────────────────────────────────────────────────
var acrName          = 'crlpaedgarsandbox'
var keyVaultName     = 'kv-lpa-edgar-sbx'
var logWorkspaceName = 'log-lpa-edgar-sandbox'
var envName          = 'cae-lpa-edgar-sandbox'
var identityName     = 'id-lpa-edgar-sandbox'
var backendAppName   = 'ca-edgar-backend'
var frontendAppName  = 'ca-edgar-frontend'
var aiStorageName    = 'stlpaedgarai'
var aiHubName        = 'aih-lpa-edgar-sandbox'
var aiProjectName    = 'aip-lpa-edgar-sandbox'
var qwenEndpointName = 'qwen32b'

// Qwen-32b from Alibaba Cloud via the Azure AI Foundry model catalog.
// Update the version number if a newer one is available in the azureml-qwen registry.
var qwenModelId = 'azureml://registries/azureml-qwen/models/Qwen2.5-32B-Instruct/versions/6'

var azureTenantId = '0513f305-0dbb-4e4e-b311-98405b8dc943'
var azureClientId = 'cffd2bfb-d624-4ddb-9850-fe5fe19f6bf5'

// Placeholder used on first deploy before real images are in ACR
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// ── Managed identity ──────────────────────────────────────────────────────────
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

// ── Container Registry ────────────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// ── Key Vault ─────────────────────────────────────────────────────────────────
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// ── Log Analytics ─────────────────────────────────────────────────────────────
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logWorkspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Storage account for AI Foundry Hub ───────────────────────────────────────
resource aiStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: aiStorageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2' }
}

// ── Azure AI Foundry Hub ──────────────────────────────────────────────────────
resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' = {
  name: aiHubName
  location: location
  kind: 'Hub'
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Basic', tier: 'Basic' }
  properties: {
    storageAccount: aiStorage.id
    keyVault: kv.id
    containerRegistry: acr.id
    friendlyName: 'EDGAR AI Foundry'
  }
}

// ── Azure AI Foundry Project ──────────────────────────────────────────────────
resource aiProject 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' = {
  name: aiProjectName
  location: location
  kind: 'Project'
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Basic', tier: 'Basic' }
  properties: {
    hubResourceId: aiHub.id
    friendlyName: 'EDGAR'
  }
}

// ── Qwen-32b Serverless Endpoint ──────────────────────────────────────────────
// Pay-per-token MaaS endpoint exposing an OpenAI-compatible API.
resource qwenEndpoint 'Microsoft.MachineLearningServices/workspaces/serverlessEndpoints@2024-07-01-preview' = {
  name: qwenEndpointName
  parent: aiProject
  location: location
  sku: { name: 'Consumption' }
  properties: {
    modelSettings: { modelId: qwenModelId }
    authMode: 'Key'
  }
}

// ── Container Apps Environment ────────────────────────────────────────────────
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

// ── Backend Container App ─────────────────────────────────────────────────────
// Secrets (anthropic-api-key, azure-ai-api-key) are KV references read via the
// managed identity. The identity must have Key Vault Secrets User on the KV
// before the container starts — see infra/assign-roles.sh.
resource backend 'Microsoft.App/containerApps@2024-03-01' = {
  name: backendAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: false
        targetPort: 8000
        transport: 'http'
      }
      registries: [{
        server: acr.properties.loginServer
        identity: identity.id
      }]
      secrets: [
        {
          name: 'anthropic-api-key'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/anthropic-api-key'
          identity: identity.id
        }
        {
          name: 'azure-ai-api-key'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/azure-ai-api-key'
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [{
        name: 'backend'
        image: placeholderImage
        env: [
          { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
          { name: 'AZURE_AI_ENDPOINT', value: qwenEndpoint.properties.inferenceEndpoint.uri }
          { name: 'AZURE_AI_API_KEY',  secretRef: 'azure-ai-api-key' }
          { name: 'AZURE_AI_MODEL',    value: 'Qwen2.5-32B-Instruct' }
          { name: 'AZURE_TENANT_ID',   value: azureTenantId }
          { name: 'AZURE_CLIENT_ID',   value: azureClientId }
        ]
        resources: {
          cpu: json('0.5')
          memory: '1Gi'
        }
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ── Frontend Container App ────────────────────────────────────────────────────
resource frontend 'Microsoft.App/containerApps@2024-03-01' = {
  name: frontendAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 5173
        transport: 'http'
      }
      registries: [{
        server: acr.properties.loginServer
        identity: identity.id
      }]
    }
    template: {
      containers: [{
        name: 'frontend'
        image: placeholderImage
        env: [
          { name: 'VITE_BACKEND_URL',     value: 'http://${backendAppName}' }
          { name: 'VITE_AZURE_TENANT_ID', value: azureTenantId }
          { name: 'VITE_AZURE_CLIENT_ID', value: azureClientId }
        ]
        resources: {
          cpu: json('0.25')
          memory: '0.5Gi'
        }
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────
output acrLoginServer  string = acr.properties.loginServer
output frontendFqdn    string = frontend.properties.configuration.ingress.fqdn
output qwenEndpointUrl string = qwenEndpoint.properties.inferenceEndpoint.uri
output keyVaultName    string = kv.name
output identityId      string = identity.id
output identityPrincipalId string = identity.properties.principalId
output aiHubPrincipalId    string = aiHub.identity.principalId
