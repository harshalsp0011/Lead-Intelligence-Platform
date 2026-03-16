# Dashboard Frontend Service
# React-based UI for lead management platform

FROM node:18-alpine

WORKDIR /app

# Install simple HTTP server to serve frontend
RUN npm install -g serve

# Copy source files
COPY dashboard/src ./src

# Expose port
EXPOSE 3000

# Serve frontend files
CMD ["serve", "-s", "src", "-l", "3000"]
