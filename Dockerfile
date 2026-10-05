FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python manage.py collectstatic --no-input && python manage.py migrate && python manage.py createsuperuser --noinput || true && gunicorn local_parakeet.wsgi:application --bind 0.0.0.0:8000"]
