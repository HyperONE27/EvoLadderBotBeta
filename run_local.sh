#!/bin/bash

# Start backend
uv run uvicorn backend.api.app:app --host 0.0.0.0 --port 8080 &
BACKEND_PID=$!

# Start bot
uv run python -m bot.core.app &
BOT_PID=$!

# Start channel manager
uv run uvicorn channel_manager.app:app --host 0.0.0.0 --port 8090 &
CHANNEL_MANAGER_PID=$!

# Kill all three on Ctrl+C
trap "kill $BACKEND_PID $BOT_PID $CHANNEL_MANAGER_PID" SIGINT SIGTERM

wait
