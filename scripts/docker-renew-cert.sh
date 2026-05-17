#!/bin/sh
set -eu

: "${TS_HOSTNAME:?TS_HOSTNAME must be set}"
: "${TS_TAILNET:?TS_TAILNET must be set}"
DOMAIN="${TS_HOSTNAME}.${TS_TAILNET}"
CERT_DIR="/certs"
CERT_FILE="$CERT_DIR/$DOMAIN.crt"
WARN_DAYS=14

renew() {
    echo "$(date): Renewing cert for $DOMAIN"
    tailscale cert --cert-file "$CERT_DIR/$DOMAIN.crt" --key-file "$CERT_DIR/$DOMAIN.key" "$DOMAIN"
    echo "$(date): Cert renewed successfully"
}

check_and_renew() {
    if [ ! -f "$CERT_FILE" ]; then
        echo "$(date): No cert found. Generating..."
        renew
        return
    fi

    days_left=$(openssl x509 -enddate -noout -in "$CERT_FILE" \
        | sed 's/notAfter=//' \
        | { read expiry; expr '(' "$(date -d "$expiry" +%s)" - "$(date +%s)" ')' / 86400; } 2>/dev/null || echo 0)

    echo "$(date): Cert expires in ${days_left} days"

    if [ "$days_left" -le "$WARN_DAYS" ]; then
        renew
    else
        echo "$(date): No renewal needed"
    fi
}

# Run once at startup
check_and_renew

# Then check weekly
while true; do
    sleep 604800  # 7 days
    check_and_renew
done
