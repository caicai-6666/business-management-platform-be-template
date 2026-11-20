FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /template
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY tests/check_search.py tests/check_middleware.py tests/
COPY main.py .
RUN mkdir -p tests/tmp
CMD ["python", "tests/check_search.py"]
