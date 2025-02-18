FROM node:18-alpine

WORKDIR /app

# Copy package.json first to leverage Docker cache
COPY package.json ./

# Install dependencies
RUN npm install

# Then copy the rest of the application
COPY . .

# Set the API URL to use the service name from docker-compose
ENV REACT_APP_API_URL=http://localhost:8000

EXPOSE 3000

# Add this to ensure the container waits for the API to be ready
CMD ["npm", "start"] 