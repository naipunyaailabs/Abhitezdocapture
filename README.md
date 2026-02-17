# Docapture AI

AI-powered document extraction and analysis platform.

## 🚀 Quick Start

### 1. Prerequisites
- Docker and Docker Compose
- API Keys for Groq/OpenAI

### 2. Configuration
Copy the example environment file and fill in your credentials:
```bash
cp .env.example .env
```

### 3. Run with Docker
```bash
docker-compose up --build
```
The application will be available at `http://localhost:5000`.

## 🛠 Features
- **General Extraction**: AI-powered structured data extraction.
- **Invoice Processing**: Specialized extraction for financial documents.
- **RFP Summarization**: Intelligent summarization of request for proposals.
- **SEO Ready**: Automated `sitemap.xml` and `robots.txt` generation.

## 📁 Project Structure
- `app/`: Main application code (FastAPI).
- `app/static/`: Static assets and SEO files.
- `app/templates/`: Jinja2 HTML templates.
- `Dockerfile`: Production-ready container configuration.
- `docker-compose.yml`: Local orchestration setup.

## 📄 License
Proprietary - Naipunya AI Labs.
