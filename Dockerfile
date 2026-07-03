FROM python:3.10-slim

# System dependencies for audio and phonemization
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        espeak-ng \
        ffmpeg \
        libsndfile1 \
        wget && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the Kokoro model into the image so it's baked in
# This avoids re-downloading on first startup after a rebuild
RUN python -c "\
import warnings; \
warnings.filterwarnings('ignore'); \
from kokoro import KPipeline; \
KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M', device='cpu')" && \
    echo "Model pre-downloaded successfully"

# Copy source code LAST (most frequently changed layer)
COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
