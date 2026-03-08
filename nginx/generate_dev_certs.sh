#!/usr/bin/env bash
# nginx/generate_dev_certs.sh
#
# Generates a self-signed TLS certificate for LOCAL DEVELOPMENT only.
# The cert covers localhost and 127.0.0.1 via Subject Alternative Names.
#
# Usage:
#   bash nginx/generate_dev_certs.sh
#
# For production, replace with real certificates:
#   certbot certonly --standalone -d yourdomain.com
#   cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/certs/server.crt
#   cp /etc/letsencrypt/live/yourdomain.com/privkey.pem   nginx/certs/server.key

set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 \
    -nodes \
    -days 365 \
    -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out    "$CERT_DIR/server.crt" \
    -subj   "/CN=localhost/O=DeepRouter Dev/C=US" \
    -addext "subjectAltName=DNS:localhost,DNS:api,IP:127.0.0.1"

echo ""
echo "Dev certificates written to: $CERT_DIR"
echo "  server.crt  (certificate)"
echo "  server.key  (private key)"
echo ""
echo "WARNING: These are SELF-SIGNED — browsers will warn."
echo "         Add an exception, or trust the cert in your OS keychain."
echo "         NEVER use self-signed certs in production."
