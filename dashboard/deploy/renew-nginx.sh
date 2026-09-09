#!/bin/sh
# Certbot runs deployment hooks only after successful certificate renewal.
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
