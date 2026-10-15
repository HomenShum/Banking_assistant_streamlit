# Banking Assistant Streamlit

A Streamlit research prototype for extracting company information and tables from PDFs, chatting about uploaded documents, reading business-card images, and exporting results to Excel.

The current launch target is [ragv3+chatv3+ocrv1.py](ragv3+chatv3+ocrv1.py), the file selected by the existing devcontainer. The older [ragv3+chatv1+ocrv1.py](ragv3+chatv1+ocrv1.py) remains available as an earlier implementation.

## Setup

Use Python **3.11** to match the existing [devcontainer image](.devcontainer/devcontainer.json). This is the source environment reference, not a verified minimum-version or compatibility guarantee.

```bash
git clone https://github.com/HomenShum/Banking_assistant_streamlit.git
cd Banking_assistant_streamlit
python3.11 -m venv .venv
source .venv/bin/activate
```

On Debian/Ubuntu, the existing container setup names these system dependencies:

```bash
sudo apt-get update
sudo apt-get install -y libgl1 ghostscript python3-tk
python -m pip install -r requirements.txt
```

For a Windows virtual environment, select Python 3.11 with `py -3.11 -m venv .venv` and activate it with `.venv\Scripts\Activate.ps1`. The system-package commands above target Debian/Ubuntu; a native Windows PDF stack has not been verified by this change.

Before launching, configure **OPENAI_API_KEY** in **Streamlit secrets**, which the scripts read through `st.secrets`. A local Streamlit installation uses `.streamlit/secrets.toml`; hosted installations use their own secrets configuration. There is no tracked `.gitignore` in this checkout, so do not assume a local secrets file is excluded from Git. Keep the value out of source and commits; this guide supplies the key name only.

## Launch

From the repository root with the virtual environment active:

```bash
streamlit run "ragv3+chatv3+ocrv1.py"
```

This command uses Streamlit's local defaults. The application's upload/process and chat controls trigger provider-backed work; merely correcting the filename does not establish that the app starts or processes documents successfully.

## Where document content is used

The PDF processing code saves the upload temporarily, reads it locally with PyMuPDF/Camelot, and passes the saved PDF path to `LayoutPDFReader.read_pdf`, configured for LLMSherpa's hosted `readers.llmsherpa.com` parser. Table summaries send extracted table JSON to OpenAI. Chat helpers also make OpenAI calls using prompts, context and conversation history. The image/OCR path base64-encodes the uploaded image and posts that payload to OpenAI.

These are source-observed call paths, not a verified transport trace or an inspection of the installed SDK's internals. Choose documents suitable for those configured external processing paths.

## Compatibility and proof limits

This is a **source-only** onboarding correction. Clean dependency installation, application startup, PDF/OCR processing, provider availability, model outputs and the rendered UI were **not verified** by this change.

[requirements.txt](requirements.txt) is **unpinned**. The scripts use legacy LlamaIndex import paths and older configured model names; compatible dependency versions and current provider support need a separate measured baseline. This guide does not certify that installing the newest packages will work. Neither application script, the dependency list, nor the devcontainer configuration was changed.

## Source map

| File | Purpose |
| --- | --- |
| [ragv3+chatv3+ocrv1.py](ragv3+chatv3+ocrv1.py) | Devcontainer-selected application, PDF processing, image/OCR and chat |
| [ragv3+chatv1+ocrv1.py](ragv3+chatv1+ocrv1.py) | Retained earlier application |
| [requirements.txt](requirements.txt) | Unpinned Python dependencies |
| [packages.txt](packages.txt) | System package declaration: libgl1 |
| [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) | Python image, additional system packages and existing launch configuration |

See the [documentation change history](CHANGELOG/README.md) for this correction and its proof scope.

## License status

The previous README described the project as MIT. This checkout has no standalone LICENSE file. This documentation update adds no license grant.
