# 🧠 AI Group Discussion Simulator

A multi-agent Group Discussion (GD) simulation engine built using FastAPI and local LLMs (Ollama + Phi3).  
This system simulates a real interview-style GD environment with a Moderator, multiple Participants, and an Evaluator.

---

## 🚀 Overview

This project allows users to practice group discussions in a structured, turn-based environment.

The system includes:

- 🧑‍⚖️ Moderator – Introduces and controls the discussion
- 🧠 AI Participants – Respond with different debating styles
- 🎯 Evaluator – Scores user performance based on the full transcript

Unlike a simple chatbot, this is a stateful multi-agent simulation engine with session memory and structured evaluation.

---

## 🏗️ Architecture
```
root/
│
├── app/
│ ├── api/ # API routes
│ ├── core/ # Model config & Ollama client
│ ├── models/ # Session state model
│ ├── services/ # Moderator, participants, evaluator logic
│ └── storage/ # In-memory session store
│
├── requirements.txt
└── run.py
```

### Key Design Concepts

- Session-based state management  
- Turn orchestration engine  
- Persona-driven AI participants  
- Transcript-based evaluation  
- Modular and scalable backend structure  

---

## 🛠️ Tech Stack

- **Backend:** FastAPI  
- **Model Runtime:** Ollama  
- **Model:** Phi3 (local execution)  
- **Language:** Python  






