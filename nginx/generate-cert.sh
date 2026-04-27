#!/usr/bin/env bash
# Generates a self-signed TLS certificate valid for 10 years.
# Run once from the repo root: bash nginx/generate-cert.sh

set -euo pipefail

CERTS_DIR="$(dirname "$0")/certs"
mkdir -p "$CERTS_DIR"

if [ -f "$CERTS_DIR/cert.pem" ] && [ -f "$CERTS_DIR/key.pem" ]; then
    echo "Certificate already exists at $CERTS_DIR — skipping."
    exit 0
fi

# Try to get the server's IP for the SAN
SERVER_IP=$(hostname -I | awk '{print $1}')

openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout "$CERTS_DIR/key.pem" \
    -out    "$CERTS_DIR/cert.pem" \
    -days   3650 \
    -subj   "/C=DE/O=LPA/CN=edgar.l-p-a.dev" \
    -addext "subjectAltName=IP:${SERVER_IP},DNS:edgar.l-p-a.dev,DNS:localhost"

echo "Certificate generated at $CERTS_DIR"
echo "  Valid for IP : $SERVER_IP"
echo "  Valid for DNS: edgar.l-p-a.dev, localhost"
