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
IDENTITY="id-lpa-edgar-sandbox"
AI_HUB="aih-lpa-edgar-sandbox"

echo "Fetching resource IDs and principal IDs..."

ACR_ID=$(az acr show \
  --name "$ACR" --resource-group "$RG" \
  --query id -o tsv)

KV_ID=$(az keyvault show \
  --name "$KV" --resource-group "$RG" \
  --query id -o tsv)

IDENTITY_PRINCIPAL=$(az identity show \
  --name "$IDENTITY" --resource-group "$RG" \
  --query principalId -o tsv)

AI_HUB_PRINCIPAL=$(az ml workspace show \
  --name "$AI_HUB" --resource-group "$RG" \
  --query identity.principal_id -o tsv 2>/dev/null || echo "")

echo "  Managed identity principal : $IDENTITY_PRINCIPAL"
echo "  AI Hub principal           : ${AI_HUB_PRINCIPAL:-<not found>}"
echo "  ACR resource ID            : $ACR_ID"
echo "  Key Vault resource ID      : $KV_ID"
echo ""

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

if [ -n "$AI_HUB_PRINCIPAL" ]; then
  echo "Assigning Key Vault Secrets Officer to AI Foundry Hub on Key Vault..."
  az role assignment create \
    --assignee-object-id "$AI_HUB_PRINCIPAL" \
    --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets Officer" \
    --scope "$KV_ID"
else
  echo "Skipping AI Hub role assignment (hub not yet deployed or ml extension missing)."
fi

echo ""
echo "Assigning AcrPush to pipeline service principal on ACR..."
PIPELINE_SP=$(az ad sp list --display-name "azure-edgar" --query "[0].id" -o tsv 2>/dev/null || echo "")
if [ -n "$PIPELINE_SP" ]; then
  az role assignment create \
    --assignee-object-id "$PIPELINE_SP" \
    --assignee-principal-type ServicePrincipal \
    --role "AcrPush" \
    --scope "$ACR_ID"
else
  echo "  Could not auto-find the pipeline SP — assign AcrPush manually in the portal on:"
  echo "  $ACR_ID"
fi

echo ""
echo "Done. Role assignments complete."
