# PDF JavaScript Sanitizer

## Overview

This Python script provides tools to check PDF files for embedded JavaScript actions and optionally remove them, saving a sanitized version of the file. JavaScript in PDFs can potentially be used for malicious purposes (e.g., triggering exploits, phoning home), so removing it can be a useful security measure.

## Features

* **Check for JavaScript:** Scans a PDF for JavaScript actions associated with document-level events (like OpenAction), page-level events, and annotation actions.
* **Remove JavaScript:** Creates a new PDF file with detected JavaScript actions removed. The removal process involves deleting the specific dictionary keys or array elements associated with JavaScript actions.
* **Verbose Logging:** Includes an optional `-v` flag for detailed logging of the checking and removal process.

## Prerequisites

* Python 3.6+
* pip (Python package installer)

## Installation

1. **Clone the repository (if applicable) or download `pdf_sanitizer.py`.**
2. **Install the required library (`pikepdf`):**

    ```bash
    pip install pikepdf
    ```

## Usage

The script uses command-line arguments to perform actions.

**Basic Syntax:**

```bash
python pdf_sanitizer.py [options] <command> [command-options]
```

**Commands:**

* `check`: Checks a PDF file for JavaScript.
* `remove`: Removes JavaScript from a PDF and saves it to a new file.

**Options:**

* `-h`, `--help`: Show help message and exit.
* `-v`, `--verbose`: Enable detailed debug logging.

**Examples:**

1. **Check a PDF for JavaScript:**

    ```bash
    python pdf_sanitizer.py check /path/to/your/document.pdf
    ```

2. **Check a PDF with verbose output:**

    ```bash
    python pdf_sanitizer.py -v check /path/to/your/document.pdf
    ```

3. **Remove JavaScript and save to a new file:**

    ```bash
    python pdf_sanitizer.py remove /path/to/input.pdf /path/to/output_sanitized.pdf
    ```

4. **Remove JavaScript with verbose output:**

    ```bash
    python pdf_sanitizer.py -v remove /path/to/input.pdf /path/to/output_sanitized.pdf
    ```

## How it Works

The script uses the `pikepdf` library to parse the PDF structure.

* **Checking:** It recursively traverses the PDF's object structure, looking for dictionary keys like `/A`, `/OpenAction`, `/AA` (Additional Actions), and `/JS` within name trees that contain JavaScript actions (identified by `/S` key being `/JavaScript`).
* **Removal:** When the `remove` command is used, it identifies the JavaScript actions similarly to the check process. Instead of just reporting them, it modifies the PDF structure *in memory* by deleting the dictionary keys or array elements containing the JavaScript action. It uses a multi-pass approach, rescanning the document multiple times and explicitly checking page annotations in each pass to ensure thorough removal, even in complex structures. The modified PDF object is then saved to the specified output file.

## Disclaimer

While this tool aims to remove known types of JavaScript actions, PDF structures can be complex. There's no absolute guarantee it will remove *every* conceivable form of embedded script or active content, especially in maliciously crafted files. Always exercise caution when handling PDFs from untrusted sources.
