#!/bin/bash
echo "Starting Ad Ops Multi-Agent System..."

if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
  echo "Please edit .env and add your GROQ_API_KEY"
  exit 1
fi

echo "Starting backend..."
pip install -r requirements.txt -q
uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

echo "Starting frontend..."
cd frontend
npm install --silent 2>/dev/null
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "System is running!"
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:5173"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
