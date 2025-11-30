<p align="center">
  <img src="https://raw.githubusercontent.com/gavrielc/Nano-PDF/main/assets/Nano%20PDF.png" alt="Nano PDF Logo" width="300"/>
</p>

# Nano PDF Editor

[![PyPI version](https://badge.fury.io/py/nano-pdf.svg)](https://badge.fury.io/py/nano-pdf)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A CLI tool to edit PDF slides using natural language prompts, powered by Google's **Gemini 3 Pro Image** ("Nano Banana") model.

## Features
*   **Natural Language Editing**: "Update the graph to include data from 2025", "Change the chart to a bar graph".
*   **Add New Slides**: Generate entirely new slides that match your deck's visual style.
*   **Non-Destructive**: Preserves the searchable text layer of your PDF using OCR re-hydration.
*   **Multi-page & Parallel**: Edit multiple pages in a single command with concurrent processing.

## Example

```bash
nano-pdf edit linkedin-deck.pdf 1 "Change the tagline in the logo to 'Cringe posts from work colleagues' and update the date"
```

| Before | After |
|--------|-------|
| ![Before](https://raw.githubusercontent.com/gavrielc/Nano-PDF/main/assets/linkedin-before.png) | ![After](https://raw.githubusercontent.com/gavrielc/Nano-PDF/main/assets/linkedin-after.png) |

*[Original deck](https://www.peterfisk.com/wp-content/uploads/2025/10/LinkedIn-Pitch-Deck.-2004.-Series-B-1.pdf) from LinkedIn's 2004 Series B pitch | [Edited deck](https://github.com/gavrielc/Nano-PDF/raw/main/assets/edited_LinkedIn-Pitch-Deck.-2004.-Series-B-1.pdf)*

**Text remains selectable** - OCR re-hydration preserves the text layer:

![Text selection demo](https://raw.githubusercontent.com/gavrielc/Nano-PDF/main/assets/text-selection-demo.png)

## How It Works

Nano PDF uses Gemini 3 Pro Image (aka Nano Banana) and PDF manipulation to enable quick edits of PDFs with natural language editing:

1. **Page Rendering**: Converts target PDF pages to images using Poppler
2. **Style References**: Optionally includes style reference pages with generation request to understand visual style (fonts, colors, layout)
3. **AI Generation**: Sends images + prompts to Gemini 3 Pro Image, which generates edited versions
4. **OCR Re-hydration**: Uses Tesseract to restore searchable text layer to generated images
5. **PDF Stitching**: Replaces original pages with AI-edited versions while preserving document structure

The tool processes multiple pages in parallel for speed, with configurable resolution (4K/2K/1K) to balance quality vs. cost.

## Installation

```bash
pip install nano-pdf
```

## Configuration

You need a **paid** Google Gemini API key with billing enabled. Free tier keys do not support image generation.

1. Get an API key from [Google AI Studio](https://aistudio.google.com/api-keys)
2. Enable billing on your Google Cloud project
3. Set it as an environment variable:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

**Note:** This tool uses Gemini 3 Pro Image which requires a paid API tier. See [pricing](https://ai.google.dev/pricing) for details.

## Usage

### Basic Edit
Edit a single page (e.g., Page 2):

```bash
nano-pdf edit my_deck.pdf 2 "Change the title to 'Q3 Results'"
```

### Multi-page Edit
Edit multiple pages in one go:

```bash
nano-pdf edit my_deck.pdf \
  1 "Update date to Oct 2025" \
  5 "Add company logo" \
  10 "Fix typo in footer"
```

### Add New Slides
Insert a new AI-generated slide into your deck:

```bash
# Add a title slide at the beginning
nano-pdf add my_deck.pdf 0 "Title slide with 'Q3 2025 Review'"

# Add a slide after page 5
nano-pdf add my_deck.pdf 5 "Summary slide with key takeaways as bullet points"
```

The new slide will automatically match the visual style of your existing slides and uses document context by default for better relevance.

### Options
*   `--use-context` / `--no-use-context`: Include the full text of the PDF as context for the model. Disabled by default for `edit`, **enabled by default for `add`**. Use `--no-use-context` to disable.
*   `--style-refs "1,5"`: Manually specify which pages to use as style references.
*   `--output "new.pdf"`: Specify the output filename.
*   `--resolution "4K"`: Image resolution - "4K" (default), "2K", or "1K". Higher quality = slower processing.
*   `--disable-google-search`: Prevents the model from using Google Search to find information before generating (enabled by default).

## Examples

### Fixing Presentation Errors
```bash
# Fix typos across multiple slides
nano-pdf edit pitch_deck.pdf \
  3 "Fix the typo 'recieve' to 'receive'" \
  7 "Change 'Q4 2024' to 'Q1 2025'"
```

### Visual Design Changes
```bash
# Update branding and colors
nano-pdf edit slides.pdf 1 "Make the header background blue and text white" \
  --style-refs "2,3" --output branded_slides.pdf
```

### Content Updates
```bash
# Update financial data
nano-pdf edit report.pdf 12 "Update the revenue chart to show Q3 at $2.5M instead of $2.1M"
```

### Batch Processing with Context
```bash
# Use full document context for consistency
nano-pdf edit presentation.pdf \
  5 "Update the chart colors to match the theme" \
  8 "Add the company logo in the bottom right" \
  --use-context
```

### Adding New Slides
```bash
# Add a new agenda slide at the beginning
nano-pdf add quarterly_report.pdf 0 "Agenda slide with: Overview, Financial Results, Q4 Outlook"
```

### Using Google Search
```bash
# Google Search is enabled by default - the model can look up current information
nano-pdf edit deck.pdf 5 "Update the market share data to latest figures"

# Disable Google Search if you want the model to only use provided context
nano-pdf add deck.pdf 3 "Add a summary slide" --disable-google-search
```

## Requirements
*   Python 3.10+
*   `poppler` (for PDF rendering)
*   `tesseract` (for OCR)

### System Dependencies

#### macOS
```bash
brew install poppler tesseract
```

#### Windows
```bash
choco install poppler tesseract
```

**Note:** After installation, you may need to restart your terminal or add the installation directory to your PATH.

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get install poppler-utils tesseract-ocr
```

## Troubleshooting

### "Missing system dependencies" error
Make sure you've installed poppler and tesseract for your platform. After installation, restart your terminal to refresh PATH. Run `which pdftotext` and `which tesseract` to verify they're accessible.

### "GEMINI_API_KEY not found" error
Set your API key as an environment variable:
```bash
export GEMINI_API_KEY="your_key_here"
```

### "Gemini API Error: PAID API key required" error
Gemini 3 Pro Image requires a paid API tier. Visit [Google AI Studio](https://aistudio.google.com/api-keys) to enable billing on your project.

### Generated images don't match the style
Try using `--style-refs` to specify reference pages that have the desired visual style. The model will analyze these pages to better match fonts, colors, and layout.

### Text layer is missing or incorrect after editing
The tool uses Tesseract OCR to restore searchable text. For best results, ensure your generated images are high resolution (`--resolution "4K"`). Note that OCR may not be perfect for stylized fonts or small text.

### Pages are processing slowly
- Use `--resolution "2K"` or `--resolution "1K"` for faster processing

## Running from Source

If you want to run the latest development version:

```bash
# Clone the repository
git clone https://github.com/gavrielc/Nano-PDF.git
cd Nano-PDF

# Install dependencies
pip install -e .

# Run the tool
nano-pdf edit my_deck.pdf 2 "Your edit here"
```

## License
MIT
