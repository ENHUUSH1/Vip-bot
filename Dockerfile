FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Database хадгалах volume

ENV BOT_TOKEN=""
ENV ADMIN_ID_1=""
ENV ADMIN_ID_2=""
ENV VIP_GROUP_ID=""

CMD ["python", "bot.py"]
