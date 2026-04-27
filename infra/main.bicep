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
//
// NOTE: Data is ephemeral in this sandbox configuration (SQLite lives in the
// container). Add an Azure Files mount and migrate to WAL-safe storage before
// promoting to production.

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

var azureTenantId  = '0513f305-0dbb-4e4e-b311-98405b8dc943'
var azureClientId  = 'cffd2bfb-d624-4ddb-9850-fe5fe19f6bf5'

// Placeholder image used on first deploy before real images exist in ACR
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// ── Managed identity ──────────────────────────────────────────────────────────
// Created first so role assignments can reference its principalId before
// the Container Apps are provisioned.
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

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
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

var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, identity.id, kvSecretsUserRoleId)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
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
// Internal ingress only — not reachable from the internet.
// The Anthropic API key is read from Key Vault at runtime via the managed identity.
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
      secrets: [{
        name: 'anthropic-api-key'
        keyVaultUrl: '${kv.properties.vaultUri}secrets/anthropic-api-key'
        identity: identity.id
      }]
    }
    template: {
      containers: [{
        name: 'backend'
        image: placeholderImage
        env: [
          { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
          { name: 'AZURE_TENANT_ID', value: azureTenantId }
          { name: 'AZURE_CLIENT_ID', value: azureClientId }
        ]
        resources: {
          cpu: json('0.5')
          memory: '1Gi'
        }
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPull, kvSecretsUser]
}

// ── Frontend Container App ────────────────────────────────────────────────────
// External ingress — the public entry point for users.
// VITE_BACKEND_URL points to the backend's internal Container Apps hostname.
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
          { name: 'VITE_BACKEND_URL', value: 'http://${backendAppName}' }
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
  dependsOn: [acrPull]
}

// ── Outputs ───────────────────────────────────────────────────────────────────
output acrLoginServer string = acr.properties.loginServer
output frontendFqdn string = frontend.properties.configuration.ingress.fqdn
output keyVaultName string = kv.name
