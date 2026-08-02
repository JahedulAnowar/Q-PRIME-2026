.PHONY: up down logs clean test reproduce dev llm

up:            ## Start the analysis and query applications
	docker compose up -d --build

down:          ## Stop the applications
	docker compose down

clean:         ## Stop the applications and remove the optional model volume
	docker compose down -v

logs:          ## Tail application logs
	docker compose logs -f qprime-analysis qprime-nlp qprime-query

llm:           ## Start the optional local LLM and pull its model
	docker compose --profile llm up -d ollama
	docker compose --profile llm exec ollama ollama pull "$${MODEL:-qwen2.5:7b-instruct-q4_K_M}"

test:          ## Run the retained algorithm and NLP tests
	python -m pytest tests/ -v

reproduce:     ## Run the paper's algorithms over its representative records
	python scripts/reproduce_paper.py

dev:           ## Run the Python APIs locally; run npm separately for the web UI
	python services/core/app.py & \
	python services/nlp/app.py & \
	wait
