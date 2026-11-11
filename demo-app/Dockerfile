FROM python:3.12-slim

# Pick up security fixes for the base image's system packages and for pip itself.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --only-binary :all: pip==26.3 setuptools==84.2.1

WORKDIR /srv
# requirements.lock has the exact version of every package (made from requirements.txt).
# --only-binary stops pip from running a package's own setup script during install.
COPY requirements.lock .
RUN pip install --no-cache-dir --only-binary :all: -r requirements.lock
COPY app ./app

# Do not run as root inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
