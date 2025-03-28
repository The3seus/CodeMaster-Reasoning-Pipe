# 🧠 CodeMaster Reasoning Pipe

**Version:** 0.0.2  
**Author:** [Sam Paniagua](https://theeseus.dev)  
**Email:** [theeseus@protonmail.com](mailto:theeseus@protonmail.com)  
**LinkedIn:** [@theeseus](https://www.linkedin.com/in/theeseus)

---

## 🚀 Overview

`CodeMaster Reasoning Pipe` is an experimental reasoning framework designed to extend the capabilities of modern LLM chat UIs by integrating structured, iterative thinking directly into the pipeline. Inspired by cognitive architectures and multi-model orchestration, it introduces a "reasoning pipe" model that can:

- Perform **initial reasoning breakdowns**
- Iteratively refine solutions via **Chain-of-Thought (CoT)**
- Generate precise, context-aware **final responses**

This project is especially useful for:
- Enhancing explainability in AI systems  
- Testing multi-model reasoning with OpenAI or Ollama  
- Debugging complex prompts and logic chains  
- Building AI agents with a transparent reasoning trace

---

## 🧩 Key Features

- 🛠 **Model Routing**: Dynamically switch between OpenAI and Ollama for both reasoning and response stages.
- 🔁 **Chain-of-Thought Iterations**: Tunable multi-pass reasoning to refine logical plans.
- 💬 **Reasoning Trace**: Optional traceable reasoning output for debugging and transparency.
- ⏱ **Timeout Handling**: Max reasoning time to prevent runaway processes.
- 🧪 **Plug-and-Play**: Designed for integration with Open WebUI and modular LLM backends.

---

## 🧬 Architecture

```mermaid
graph LR
A[User Query] --> B[Initial Reasoning]
B --> C[Chain of Thought Iterations]
C --> D[Final Response Generation]
D --> E[Response Returned to UI]
