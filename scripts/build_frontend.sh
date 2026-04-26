#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../frontend-realestate"
npm install
npm run build
