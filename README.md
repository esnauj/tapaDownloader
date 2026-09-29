# tapaDownloader

A Windows desktop application for searching album releases in MusicBrainz, downloading artwork from the Cover Art Archive, and preparing covers for print with optional Real-ESRGAN upscaling.

## Features

- Search for artists, albums, EPs, and singles.
- Automatically select the best available front cover.
- Compare multiple releases before downloading.
- Download individual covers or process batches.
- Import plain text lists or CSV files.
- Retry only failed batch entries.
- Upscale small covers with Real-ESRGAN ncnn-vulkan.
- Prepare output with 300 DPI metadata for printing.
- Track resolution, DPI, quality, and visual duplicates.
- Browse the local cover collection.
- Select covers from the collection and export one cover per PDF page.
- Export print PDFs as A4 or A3 with RGB, CMYK, or grayscale output, selectable DPI,
  lossless image output, JPEG output, and configurable bleed.
- Use output presets for posters, master files, digital covers, and vinyl.

## Requirements

- Windows 10 or newer.
- Python 3.10 or newer.
- `requests` and `Pillow`.
- Real-ESRGAN ncnn-vulkan for AI upscaling.

## Installation

Open PowerShell in the project directory:

```powershell
python -m venv tapaDownloader.venv
.\tapaDownloader.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For editable package installation:

```powershell
.\tapaDownloader.venv\Scripts\python.exe -m pip install -e .
```

## Running the application

Recommended entry point:

```powershell
.\tapaDownloader.venv\Scripts\python.exe -m tapa_downloader
```

Compatibility launcher:

```powershell
.\tapaDownloader.venv\Scripts\python.exe portadas_gui.py
```

After editable installation, the console entry point is also available:

```powershell
tapa-downloader
```

## Local configuration and privacy

The project does not contain a personal email address, credentials, API keys, or other user secrets.

MusicBrainz requests should use an identifiable `User-Agent`. Configure your own email in `Settings...` before using the application. The value is stored in the operating system's user configuration directory, not in this repository.

Do not commit local configuration files, downloaded images, logs, or credentials. The included `.gitignore` excludes common local data and virtual environments.

The default source code contains no personal email address. Before publishing, you can verify the repository with:

```powershell
Get-ChildItem -Recurse -File | Select-String -Pattern '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
```

Matches inside `tapaDownloader.venv` belong to third-party package metadata and should not be published because the virtual environment is ignored. Do not upload `tapaDownloader.venv`.

## Real-ESRGAN setup

1. Open `Settings...` and select `AI Upscaling`.
2. Verify `realesrgan-ncnn-vulkan.exe`.
3. Use `realesrgan-x4plus` for photographic album artwork.
4. Click `Test installation`.
5. Enable AI upscaling and choose an output target, normally `4000 px`.

The application can detect the bundled executable in:

```text
realesrgan-ncnn-vulkan-20220424-windows/
```

## Print workflow

To prepare a cover for printing:

1. Enable `Upscale covers smaller than 4000 px`.
2. Enable `Ready for printing (300 DPI)`.
3. Select the desired format and download the cover.

The application preserves the aspect ratio and does not crop or distort images. The print reference is:

- poster size: `29.7 x 29.7 cm`;
- recommended minimum: `3508 x 3508 px`;
- target: `4000 x 4000 px`.

Non-square artwork keeps its original proportions and may not end at exactly `4000x4000` pixels.

To create a printable PDF from the local collection:

1. Open the `Collection` tab and select one or more covers with `Ctrl` or `Shift`.
2. Click `Generate PDF`.
3. Choose A4 or A3, color format, resolution, compression, and bleed.
4. Save the PDF. Each selected cover becomes one page and is fitted to the full page
	width without distortion; if its proportions do not fit the page, the remaining
	space is filled with white rather than cropping the artwork.

The `Lossless` option creates PNG/TIFF page images without JPEG loss. `JPEG alta` uses
high-quality JPEG pages. PDF output is rasterized at 8 bits per channel; the 16-bit
selection is accepted for workflow compatibility but normalized to 8 bits by the PDF
encoder.

## Output presets

Presets are available in `Settings...`:

- `Poster 30 cm`: JPG, 4000 px AI upscaling, and print metadata.
- `Master file`: PNG, 4000 px AI upscaling, and original preservation.
- `Digital cover`: JPG without AI upscaling.
- `12-inch vinyl`: JPG, 4000 px AI upscaling, original preservation, and print metadata.

## Batch processing

The `Batch` tab accepts plain text lists:

```text
Pink Floyd - The Wall
David Bowie - Low
```

It also accepts CSV files with two columns:

```csv
artist,album
Pink Floyd,The Wall
David Bowie,Low
```

Comma, semicolon, and tab-separated files are supported. After processing a batch, `Retry errors` retries only failed or coverless entries.

## Collection and history

- `Activity` records file path, resolution, DPI, quality, and duplicate information.
- `Collection` scans the configured download directory and opens local images.
- Automatic cover selection prioritizes square images, images without watermarks, and higher resolution.
- Release comparison supports two to six selected results.

## External services

- [MusicBrainz](https://musicbrainz.org/) for release searches.
- [Cover Art Archive](https://coverartarchive.org/) for cover images and metadata.
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN/) for local AI upscaling.

The application uses an identifiable `User-Agent` and throttles MusicBrainz requests to approximately one request per second.

## Project structure

```text
tapaDownloader/
├── tapa_downloader/
│   ├── __init__.py       # Package metadata
│   ├── __main__.py       # python -m tapa_downloader
│   ├── core.py           # Configuration, APIs, image processing, AI, and batches
│   └── app.py            # Tkinter application and orchestration
├── tests/                # Unit tests
├── realesrgan-ncnn-vulkan-20220424-windows/
├── portadas_gui.py       # Compatibility launcher
├── pyproject.toml        # Project metadata and console entry point
├── requirements.txt      # Runtime dependencies
├── .gitignore
└── README.md
```

User configuration is stored outside the repository. Downloaded artwork is not source code and should not be committed.

## Testing

```powershell
.\tapaDownloader.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The unit tests do not require internet access or a physical GPU.

## Troubleshooting

### Real-ESRGAN is not detected

Verify that the executable, the `models` directory, and the required `.param` and `.bin` files exist. Use `Settings... -> AI Upscaling -> Test installation`.

### Artwork does not meet the minimum resolution

AI upscaling can increase dimensions but cannot recreate detail that is absent from the source. The application reports when the shorter side remains below `3508 px`.

### MusicBrainz requests fail

Check the network connection, configure an identifiable email in the local settings, and avoid running multiple independent copies at the same time.

## Project status

This is a semi-professional educational project. The application is packaged as a Python module, keeps a compatibility launcher, and includes unit tests for the most sensitive processing paths.
