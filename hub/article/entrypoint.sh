#!/bin/bash
set -e
echo "Serving the GridSimEnv article on port 8080"
exec nginx -g 'daemon off;'
