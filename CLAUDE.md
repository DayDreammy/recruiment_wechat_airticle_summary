# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a WeChat article recruitment summary system that fetches articles from RSS feeds, processes them using LLM APIs, and distributes summaries via email and other platforms. The system consists of two main components:

1. **RSS Article Fetcher** (`rss_article_fetcher_enhanced.py`) - Fetches WeChat articles from RSS feeds and stores them in SQLite database with PDF generation
2. **Article Processor** (`pdfsummary.py`) - Main processing pipeline that summarizes articles using LLMs and handles distribution

## Core Architecture

### Data Flow
```
RSS Feed → RSS Fetcher → SQLite DB + PDFs → Article Processor → LLM Processing → Email/Feishu/Airtable Distribution
```

### Key Components

**RSS Article Fetcher (`rss_article_fetcher_enhanced.py`)**:
- Fetches articles from configured RSS URL
- Stores in SQLite database at `/home/yy/project/Gewechat/vxbot/data/message_monitor.db`
- Generates PDF files in `./pdfs/` directory using wkhtmltopdf
- Supports incremental updates and cron job execution

**Article Processor (`pdfsummary.py`)**:
- Main processing pipeline using ThreadPoolExecutor for parallel processing
- Integrates with multiple LLM providers (OpenAI, Zhipu, Xunfei)
- Classifies articles and extracts recruitment information
- Handles distribution via email, Feishu, and Airtable

**Database Layer (`sqldb.py`)**:
- SQLAlchemy ORM for SQLite operations
- Manages article processing state and user subscriptions
- Handles batch processing and article filtering

## Common Development Commands

### Running the System

**RSS Fetcher (Data Collection)**:
```bash
# Test run (dry run)
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py --dry-run

# Normal run with PDF generation
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py

# Skip PDF generation (faster)
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py --skip-pdf

# Verbose output
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py --verbose
```

**Article Processor (Main Pipeline)**:
```bash
# Run full processing pipeline
~/anaconda3/envs/py310/bin/python pdfsummary.py
```

### Testing

**Test PDF Generation**:
```bash
~/anaconda3/envs/py310/bin/python test_pdf_generation.py
```

**Test Bot/LLM Integration**:
```bash
~/anaconda3/envs/py310/bin/python test_bot.py
```

**Test Article Functions**:
```bash
~/anaconda3/envs/py310/bin/python test_article_functions.py
```

### Cron Job Setup

```bash
# Setup cron job for RSS fetching
chmod +x setup_cron.sh
./setup_cron.sh

# Manual cron setup (runs every hour)
(crontab -l 2>/dev/null; echo '0 * * * * cd /home/yy/project/recruiment_article_summary && /home/yy/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py >> cron.log 2>&1') | crontab -
```

## Configuration

**Main Config File**: `config.json`
- Contains API keys for OpenAI, Zhipu, Xunfei LLM providers
- Feishu and Airtable integration tokens
- Database paths and other settings

**Environment Requirements**:
- Python 3.10+ (uses conda environment `py310`)
- wkhtmltopdf for PDF generation
- SQLite database
- Dependencies: requests, beautifulsoup4, pdfkit, sqlalchemy, paddleocr

## Database Schema

**Main Table**: `wechat_articles`
- `message_id` - Unique article identifier
- `title`, `url`, `account_name` - Article metadata
- `content`, `raw_data` - Text and HTML content
- `pdf_path` - Generated PDF file path
- `created_at` - Publication timestamp
- `processed` - Processing status flag
- `article_type` - Article classification

## LLM Integration

The system supports multiple LLM providers through the `Bot` class in `bot.py`:
- OpenAI GPT models
- Zhipu GLM models
- Xunfei models

Prompt management is handled through `prompts.py` with specialized prompts for:
- Article classification
- Recruitment information extraction
- Content summarization

## Logging

- RSS fetcher logs: `rss_fetcher_enhanced.log`
- Main application logs: `/home/yy/project/recruiment_article_summary/logs/YYYY-MM-DD.log`
- Cron job logs: `cron.log`

## Key File Locations

- **Main scripts**: `rss_article_fetcher_enhanced.py`, `pdfsummary.py`
- **Database**: `/home/yy/project/Gewechat/vxbot/data/message_monitor.db`
- **PDF storage**: `./pdfs/`
- **Configuration**: `config.json`
- **Logs**: `/home/yy/project/recruiment_article_summary/logs/`

## Development Notes

- The system uses Beijing timezone (`beijing_tz`) for timestamp handling
- Processing is parallelized using ThreadPoolExecutor
- Articles are classified by type (recruitment, news, general, others) with different processing prompts
- Email distribution supports both individual and batch sending with personalized content