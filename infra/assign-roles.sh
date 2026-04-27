#!/usr/bin/env bash
# ── infra/assign-roles.sh ─────────────────────────────────────────────────────
# Run once after the first Bicep deployment to assign roles that require Owner.
# Your own Azure account must have Owner on the resource group.
#
# Usage:
#   az login
#   bash infra/assign-roles.sh

set -euo pipefail

RG="rg-lpa-edgar-sandbox-germanywestcentral"
ACR="crlpaedgarsandbox"
KV="kv-lpa-edgar-sbx"

echo "Fetching principal IDs from deployment outputs..."

IDENTITY_PRINCIPAL=$(az deployment group show \
  --resource-group "$RG" \
  --name main \
  --query properties.outputs.identityPrincipalId.value -o tsv)

AI_HUB_PRINCIPAL=$(az deployment group show \
  --resource-group "$RG" \
  --name main \
  --query properties.outputs.aiHubPrincipalId.value -o tsv)

ACR_ID=$(az acr show --name "$ACR" --resource-group "$RG" --query id -o tsv)
KV_ID=$(az keyvault show --name "$KV"  --resource-group "$RG" --query id -o tsv)

echo "Assigning AcrPull to managed identity on ACR..."
az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "AcrPull" \
  --scope "$ACR_ID"

echo "Assigning Key Vault Secrets User to managed identity on Key Vault..."
az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$KV_ID"

echo "Assigning Key Vault Secrets Officer to AI Foundry Hub identity on Key Vault..."
az role assignment create \
  --assignee-object-id "$AI_HUB_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets Officer" \
  --scope "$KV_ID"

echo "Assigning AcrPush to pipeline service principal on ACR..."
echo "(Looking up the azure-edgar service connection principal...)"
PIPELINE_SP=$(az ad sp list --display-name "azure-edgar" --query "[0].id" -o tsv 2>/dev/null || echo "")
if [ -n "$PIPELINE_SP" ]; then
  az role assignment create \
    --assignee-object-id "$PIPELINE_SP" \
    --assignee-principal-type ServicePrincipal \
    --role "AcrPush" \
    --scope "$ACR_ID"
else
  echo "  Could not auto-find the pipeline SP — assign AcrPush manually in the portal."
  echo "  ACR resource ID: $ACR_ID"
fi

echo ""
echo "Done. Role assignments complete."
