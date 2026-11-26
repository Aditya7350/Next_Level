#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "==> Building React Frontend..."
cd Frontend
npm install
npm run build
cd ..

echo "==> Installing Backend Python Dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Render Build Completed Successfully!"
