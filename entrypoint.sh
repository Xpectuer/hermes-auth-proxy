#!/bin/sh
set -e

if [ -z "$PASSWORD" ]; then
    echo "ERROR: PASSWORD environment variable is required"
    exit 1
fi

# Generate htpasswd file
echo "admin:$(echo -n "$PASSWORD" | openssl passwd -apr1 -stdin)" > /etc/nginx/.htpasswd

echo "Basic auth configured for user 'admin'"
exec "$@"
