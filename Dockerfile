FROM python:3.12-bookworm

# Set the working directory in the container
WORKDIR /usr/src/app

# Invalidate the cache
ARG CACHEBUST=1

# Copy the current directory contents into the container at /app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port Flask will run on
EXPOSE 3000

# Run the Flask app
ENTRYPOINT ["python3"]
CMD ["server.py"]
