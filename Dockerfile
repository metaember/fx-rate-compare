FROM python:3.11-slim

# Install uv
RUN pip install uv

WORKDIR /app

COPY pyproject.toml .

# Create virtual env and install dependencies with uv
RUN uv venv /venv && \
    . /venv/bin/activate && \
    uv pip install -r pyproject.toml

COPY visa_fx_backend.py .

ENV PATH="/venv/bin:$PATH"

EXPOSE 3000
CMD ["python", "visa_fx_backend.py"]