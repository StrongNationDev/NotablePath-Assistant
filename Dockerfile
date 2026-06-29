# Use an official lightweight Python image
FROM python:3.11-slim

# Set the directory inside the container where your code lives
WORKDIR /app

# Copy your requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your bot's code into the container
COPY . .

# Tell the container how to run your bot (replace main.py with your file name)
CMD ["python", "main.py"]
