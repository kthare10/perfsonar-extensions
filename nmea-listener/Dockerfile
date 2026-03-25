FROM python:3.13-slim

LABEL maintainer="kthare10@renci.org"
LABEL description="NMEA 0183 navigation data listener for ship-to-shore monitoring"

RUN groupadd -r nmea && useradd -r -g nmea -s /sbin/nologin nmea

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nmea_listener.py .

USER nmea

ENTRYPOINT ["python", "-u", "nmea_listener.py"]
