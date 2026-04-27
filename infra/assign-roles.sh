#!/usr/bin/env bash
# ── infra/assign-roles.sh ─────────────────────────────────────────────────────
# Run once after the first Bicep deployment to assign roles that require Owner.
# Usage:  az login && bash infra/assign-roles.sh

set -euo pipefail

RG="rg-lpa-edgar-sandbox-germanywestcentral"
ACR="crlpaedgarsandbox"
KV="kv-lpa-edgar-sbx"
IDENTITY="id-lpa-edgar-sandbox"
AI_HUB="aih-lpa-edgar-sandbox"

echo "Fetching resource IDs..."
ACR_ID=$(az acr show --name "$ACR" --resource-group "$RG" --query id -o tsv)
KV_ID=$(az keyvault show --name "$KV" --resource-group "$RG" --query id -o tsv)

echo "Fetching managed identity principal ID..."
IDENTITY_PRINCIPAL=$(az identity show \
  --name "$IDENTITY" --resource-group "$RG" \
  --query principalId -o tsv)

echo "Fetching AI Foundry Hub principal ID..."
AI_HUB_PRINCIPAL=$(az resource show \
  --resource-group "$RG" \
  --name "$AI_HUB" \
  --resource-type "Microsoft.MachineLearningServices/workspaces" \
  --query identity.principalId -o tsv)

echo ""
echo "  Managed identity : $IDENTITY_PRINCIPAL"
echo "  AI Hub           : $AI_HUB_PRINCIPAL"
echo ""

echo "[1/4] AcrPull → managed identity on ACR..."
az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "AcrPull" --scope "$ACR_ID"

echo "[2/4] Key Vault Secrets User → managed identity on Key Vault..."
az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID"

echo "[3/4] Key Vault Secrets Officer → AI Foundry Hub on Key Vault..."
az role assignment create \
  --assignee-object-id "$AI_HUB_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets Officer" --scope "$KV_ID"

echo "[4/4] AcrPush for pipeline — assign manually in the portal."
echo "      Go to ACR crlpaedgarsandbox → Access control (IAM) → Add role assignment"
echo "      Role: AcrPush, Member: the 'azure-edgar' service connection service principal"
echo ""
echo "Done."
