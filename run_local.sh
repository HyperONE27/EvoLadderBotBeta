#!/bin/bash

# Start backend
uvicorn backend.api.app:app --host 0.0.0.0 --port 8080 --reload &
BACKEND_PID=$!

# Start bot
python -m bot.app &
BOT_PID=$!

# Kill both on Ctrl+C
trap "kill $BACKEND_PID $BOT_PID" SIGINT SIGTERM

wait